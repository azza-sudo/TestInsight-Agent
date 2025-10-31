import json
import os
from openai import OpenAI
from dotenv import load_dotenv
import requests

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing (set it as a GitHub Actions secret).")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------- Helpers to normalize arbitrary test report shapes --------
def _from_summary(results):
    s = results.get("summary", {})
    if all(k in s for k in ("total", "passed", "failed")):
        failures = results.get("failures", [])
        return {"total": s["total"], "passed": s["passed"], "failed": s["failed"], "failures": failures}
    return None

def _from_mocha_stats(results):
    # mocha --reporter json style
    stats = results.get("stats", {})
    if stats:
        total = stats.get("tests")
        passed = stats.get("passes")
        failed = stats.get("failures")
        if total is not None and passed is not None and failed is not None:
            failures = []
            for t in results.get("failures", []):
                title = " > ".join(filter(None, [t.get("fullTitle") or t.get("title")]))
                msg = (t.get("err") or {}).get("message")
                failures.append({"title": title, "error": msg})
            return {"total": total, "passed": passed, "failed": failed, "failures": failures}
    return None

def _from_jest(results):
    # Jest aggregated results shape
    keys = results.keys()
    if {"numTotalTests", "numPassedTests", "numFailedTests"}.issubset(keys):
        total = results["numTotalTests"]
        passed = results["numPassedTests"]
        failed = results["numFailedTests"]
        failures = []
        for test_result in results.get("testResults", []):
            for assertion in test_result.get("assertionResults", []):
                if assertion.get("status") == "failed":
                    failures.append({
                        "title": " > ".join(filter(None, [
                            test_result.get("name"),
                            assertion.get("ancestorTitles") and " • ".join(assertion["ancestorTitles"]),
                            assertion.get("title"),
                        ])),
                        "error": "; ".join(msg.get("content", "") for msg in assertion.get("failureMessages", []))
                                  or (assertion.get("failureMessages") or [""])[0]
                    })
        return {"total": total, "passed": passed, "failed": failed, "failures": failures}
    return None

def _from_playwright(results):
    """
    Playwright JSON report (reporter=json) has top-level 'suites' -> specs -> tests -> results.
    We'll count one row per 'test'; a test is passed if ANY result.status == 'passed'.
    """
    if "suites" not in results:
        return None

    total = passed = failed = 0
    failures = []

    def walk_suite(suite, trail):
        nonlocal total, passed, failed, failures
        # Playwright sometimes nests suites -> (either 'specs' or 'suites')
        for child in suite.get("suites", []):
            walk_suite(child, trail + [child.get("title")])

        for spec in suite.get("specs", []):
            spec_title = spec.get("title")
            for test in spec.get("tests", []):
                test_title = test.get("title")
                total += 1
                results_list = test.get("results", [])
                statuses = [r.get("status") for r in results_list]
                is_passed = any(s == "passed" for s in statuses)
                is_failed = any(s == "failed" for s in statuses) and not is_passed
                if is_passed:
                    passed += 1
                elif is_failed:
                    failed += 1
                    # try to extract an error message
                    err = None
                    for r in results_list:
                        for e in r.get("errors", []) or r.get("error", []) or []:
                            if isinstance(e, dict):
                                err = e.get("message") or e.get("value")
                            elif isinstance(e, str):
                                err = e
                            if err:
                                break
                        if err:
                            break
                    failures.append({
                        "title": " > ".join(filter(None, trail + [spec_title, test_title])),
                        "error": err
                    })
                else:
                    # treat non-passed & non-failed (e.g., skipped, timedOut) as failed for summary strictly if they have errors
                    failed += 1
                    failures.append({
                        "title": " > ".join(filter(None, trail + [spec_title, test_title])),
                        "error": f"status={statuses}"
                    })

    for suite in results.get("suites", []):
        walk_suite(suite, [suite.get("title")])

    return {"total": total, "passed": passed, "failed": failed, "failures": failures}

def normalize_results(results: dict):
    # Try several shapes
    for parser in (_from_summary, _from_mocha_stats, _from_jest, _from_playwright):
        parsed = parser(results)
        if parsed:
            # ensure 'failures' exists
            parsed["failures"] = parsed.get("failures") or []
            return parsed

    # As a last resort, try extremely generic guesses:
    candidates = [
        ("total", "passed", "failed"),
        ("tests", "passes", "failures"),
    ]
    for t, p, f in candidates:
        if all(k in results for k in (t, p, f)):
            return {"total": results[t], "passed": results[p], "failed": results[f], "failures": results.get("failures", [])}

    raise ValueError("Unrecognized test results shape; cannot normalize.")

# --------- Your original functions, adjusted to use normalized data ---------
def load_test_results(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

def generate_summary(results):
    # Normalize into a stable structure first
    norm = normalize_results(results)
    total = norm["total"]
    passed = norm["passed"]
    failed = norm["failed"]
    failures = norm["failures"]

    # Keep prompt tolerant if failures is large
    failures_excerpt = failures[:10]  # avoid giant prompts
    prompt = (
        "You are a QA Assistant. Summarize these test results in 3 bullet points.\n"
        f"Totals — Total: {total}, Passed: {passed}, Failed: {failed}\n"
        f"Failures (sample up to 10): {json.dumps(failures_excerpt, indent=2)}\n"
        "Highlight key failure trends and concrete next-step suggestions."
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception as e:
        # Fallback summary if API call fails
        lines = [
            f"- Total: {total} | Passed: {passed} | Failed: {failed}",
            f"- Top failures: {', '.join(f['title'] for f in failures[:5]) or 'None'}",
            "- Next steps: triage failing specs, deduplicate flaky tests, and add logs/screenshots to failures."
        ]
        return "\n".join(lines)

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
    try:
        norm = normalize_results(results)
        print(f"Detected shape ✓  Total={norm['total']} Passed={norm['passed']} Failed={norm['failed']}")
    except Exception as e:
        print("❌ Could not understand test results structure.")
        raise
    print("🤖 Generating summary using AI...")
    summary = generate_summary(results)
    # send_to_slack(summary)
    print(summary)
