#!/usr/bin/env python3
"""
Robust test-results normalizer for Playwright/Jest/Mocha + text-log fallback.

Usage:
  python main.py <path-to-json> [--runlog <path-to-runlog>]

If the JSON is missing or unrecognized, we'll try to parse a Playwright console
summary from the run log so your AI report still has correct totals.
"""
import json
import os
import re
import sys
from typing import Optional

# ---- Optional OpenAI + Slack (safe if not configured) ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import requests
except Exception:
    requests = None


# ---------------- Normalizers ----------------
def _from_summary(results):
    s = results.get("summary", {})
    if all(k in s for k in ("total", "passed", "failed")):
        failures = results.get("failures", [])
        return {"total": s["total"], "passed": s["passed"], "failed": s["failed"], "failures": failures}
    return None


def _from_mocha_stats(results):
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
                        "error": "; ".join(assertion.get("failureMessages", []) or []),
                    })
        return {"total": total, "passed": passed, "failed": failed, "failures": failures}
    return None


def _from_playwright(results):
    # Playwright JSON report (reporter=json) -> suites -> specs -> tests -> results
    if "suites" not in results:
        return None

    total = passed = failed = 0
    failures = []

    def walk_suite(suite, trail):
        nonlocal total, passed, failed, failures
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
                is_failed = any(s == "failed" for s in statuses)
                is_timeout = any(s == "timedOut" for s in statuses)

                if is_passed:
                    passed += 1
                elif is_failed or is_timeout:
                    failed += 1
                    err = None
                    for r in results_list:
                        errs = r.get("errors") or ([r.get("error")] if r.get("error") else [])
                        for e in errs or []:
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
                        "error": err or f"status={statuses}",
                    })
                else:
                    # skipped/expected do not count as failed
                    pass

    for suite in results.get("suites", []):
        walk_suite(suite, [suite.get("title")])

    return {"total": total, "passed": passed, "failed": failed, "failures": failures}


def normalize_results(results: dict):
    for parser in (_from_summary, _from_mocha_stats, _from_jest, _from_playwright):
        parsed = parser(results)
        if parsed:
            parsed["failures"] = parsed.get("failures") or []
            return parsed

    # Generic shapes
    for t, p, f in (("total", "passed", "failed"), ("tests", "passes", "failures")):
        if all(k in results for k in (t, p, f)):
            return {"total": results[t], "passed": results[p], "failed": results[f],
                    "failures": results.get("failures", [])}

    raise ValueError("Unrecognized test results shape; cannot normalize.")


# ---------------- Fallbacks ----------------
def parse_text_summary(text: str) -> Optional[dict]:
    """
    Parse lines like:
      Running 15 tests using 1 worker
      ...
      4 failed
      11 passed
    """
    failed = passed = total = None
    m_failed = re.search(r"(\d+)\s+failed", text)
    m_passed = re.search(r"(\d+)\s+passed", text)
    m_total = re.search(r"Running\s+(\d+)\s+tests?", text)
    if m_failed:
        failed = int(m_failed.group(1))
    if m_passed:
        passed = int(m_passed.group(1))
    if m_total:
        total = int(m_total.group(1))
    if failed is not None and passed is not None:
        if total is None:
            total = failed + passed
        return {"total": total, "passed": passed, "failed": failed, "failures": []}
    return None


def safe_load_and_normalize(json_path: str, runlog_path: Optional[str] = None) -> dict:
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return normalize_results(raw)
    except Exception:
        if runlog_path and os.path.exists(runlog_path):
            with open(runlog_path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            parsed = parse_text_summary(txt)
            if parsed:
                return parsed
        # Last resort: what if the JSON file exists and is a stub?
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
                # Some users commit {"status":"no-tests-or-failure","suites":[]}
                if re.search(r'"suites"\s*:\s*\[\s*\]', raw_text):
                    raise ValueError("Playwright JSON contained no suites.")
            except Exception:
                pass
        raise


# ---------------- Output helpers ----------------
def generate_summary(norm: dict) -> str:
    total = norm["total"]
    passed = norm["passed"]
    failed = norm["failed"]
    failures = norm.get("failures", [])[:10]

    prompt = (
        "You are a QA Assistant. Summarize these test results in 3 bullet points.\n"
        f"Totals — Total: {total}, Passed: {passed}, Failed: {failed}\n"
        f"Failures (sample up to 10): {json.dumps(failures, ensure_ascii=False)}\n"
        "Highlight key failure trends and concrete next-step suggestions."
    )

    if not OPENAI_API_KEY or OpenAI is None:
        # Fallback plain summary (no external calls)
        bullets = [
            f"- Total: {total} | Passed: {passed} | Failed: {failed}",
            f"- Sample failures: {', '.join((f.get('title') or '—') for f in failures) or 'None'}",
            "- Next steps: update brittle selectors, verify testIDs, and keep traces/videos for flaky cases.",
        ]
        return "\n".join(bullets)

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def send_to_slack(message: str):
    if not SLACK_WEBHOOK_URL or requests is None:
        print("\n🔹 Slack not configured. Printing message locally:\n")
        print(message)
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        print("✅ Summary sent to Slack!")
    except Exception as e:
        print(f"⚠️ Slack send failed: {e}")


# ---------------- Entrypoint ----------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <results.json> [--runlog <runlog_path>]")
        sys.exit(2)

    json_path = sys.argv[1]
    runlog_path = None
    if "--runlog" in sys.argv:
        idx = sys.argv.index("--runlog")
        if idx + 1 < len(sys.argv):
            runlog_path = sys.argv[idx + 1]

    print("📊 Reading test results from:", json_path)
    if runlog_path:
        print("📝 Using run log fallback:", runlog_path)

    norm = safe_load_and_normalize(json_path, runlog_path)
    print(f"Detected shape ✓  Total={norm['total']} Passed={norm['passed']} Failed={norm['failed']}")

    print("🤖 Generating summary...")
    summary = generate_summary(norm)
    print(summary)

    # Optional: write a small AI report artifact for the workflow
    report = {
        "totals": {"total": norm["total"], "passed": norm["passed"], "failed": norm["failed"]},
        "summary": summary,
    }
    with open("ai_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("🗂  Wrote ai_report.json")


if __name__ == "__main__":
    main()
