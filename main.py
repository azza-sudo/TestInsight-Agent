import json
import os
import requests
import openai

# --- config via env (safer for CI) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

openai.api_key = OPENAI_API_KEY


def load_test_results(file_path):
    with open(file_path, "r") as f:
        return json.load(f)


def _normalize_results(raw):
    """
    Returns (summary_dict, failures_list)
    summary_dict: {'total': int, 'passed': int, 'failed': int}
    failures_list: list of failure objects/strings (best effort)
    """
    # 1) Happy path: explicit summary provided
    if isinstance(raw.get("summary"), dict):
        s = raw["summary"]
        total = int(s.get("total") or 0)
        passed = int(s.get("passed") or 0)
        failed = int(
            s.get("failed")
            or s.get("failures")
            or max(total - passed, 0)
        )
        failures = raw.get("failures") or raw.get("failed") or raw.get("failedTests") or []
        return {"total": total, "passed": passed, "failed": failed}, failures

    # 2) Derive from tests/specs/results arrays
    tests = (
        raw.get("tests")
        or raw.get("specs")
        or raw.get("results")
        or raw.get("cases")
        or []
    )

    if isinstance(tests, list) and tests:
        def status_of(t):
            # try common fields
            return (
                t.get("status")
                or t.get("outcome")
                or t.get("state")
                or t.get("result")
                or ""
            ).lower()

        total = len(tests)
        passed = sum(1 for t in tests if status_of(t) in {"passed", "ok", "success", "succeeded"})
        failed = sum(1 for t in tests if status_of(t) in {"failed", "fail", "broken", "error"})

        # failures list: prefer explicit; else pull failed tests
        failures = raw.get("failures")
        if not isinstance(failures, list):
            failures = [t for t in tests if status_of(t) in {"failed", "fail", "broken", "error"}]

        return {"total": total, "passed": passed, "failed": failed}, failures

    # 3) Nothing matched → helpful error
    top_keys = ", ".join(sorted(raw.keys()))
    raise KeyError(
        "Could not find 'summary' or a tests array to derive one. "
        f"Top-level keys present: {top_keys}"
    )


def generate_summary(results):
    summary, failures = _normalize_results(results)

    # Make failures compact if they’re huge
    def trim_failures(fails, limit=5):
        if not isinstance(fails, list):
            return fails
        if len(fails) <= limit:
            return fails
        return fails[:limit] + [f"... and {len(fails) - limit} more"]

    prompt = f"""
You are a QA Assistant. Summarize these test results in exactly 3 concise bullet points.
Totals — Total: {summary['total']}, Passed: {summary['passed']}, Failed: {summary['failed']}.
Failures (sample): {json.dumps(trim_failures(failures), indent=2, ensure_ascii=False)}
Focus on: 1) Main pass/fail picture, 2) Top failure patterns (by component/test), 3) Next-step suggestions.
"""

    # If you're on the newer OpenAI SDK, use client.chat.completions.create(...)
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response["choices"][0]["message"]["content"]


def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("\n🔹 Slack not configured. Printing message locally:\n")
        print(message)
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    print("✅ Summary sent to Slack!")


if __name__ == "__main__":
    print("📊 Reading test results...")
    results = load_test_results("sample_results.json")
    print("🤖 Generating summary using AI...")
    try:
        summary = generate_summary(results)
    except KeyError as e:
        # Surface a clear, actionable message in CI logs
        print(f"❌ Could not normalize test results: {e}")
        # Optional: print a preview of structure for debugging
        print("🔎 Top-level keys:", list(results.keys())[:20])
        raise
    send_to_slack(summary)
