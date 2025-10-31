#!/usr/bin/env python3
import sys, json, pathlib, os

# ---- your existing function (unchanged) ----
def _normalize_results(raw):
    """
    Returns (summary_dict, failures_list)
    summary_dict: {'total': int, 'passed': int, 'failed': int}
    failures_list: list of failure dicts/strings
    """
    # 0) Playwright stats (preferred when present)
    if isinstance(raw.get("stats"), dict):
        st = raw["stats"]
        expected = int(st.get("expected") or 0)   # passed
        unexpected = int(st.get("unexpected") or 0)  # failed
        total = expected + unexpected + int(st.get("flaky") or 0) + int(st.get("skipped") or 0)
        failures = []

        def walk(node):
            for spec in (node.get("specs") or []):
                ok = spec.get("ok")
                if ok is False:
                    fail = {"title": spec.get("title"), "file": spec.get("file"), "line": spec.get("line")}
                    msgs = []
                    for t in (spec.get("tests") or []):
                        for r in (t.get("results") or []):
                            if (r.get("status") or "").lower() == "failed":
                                msg = None
                                if isinstance(r.get("error"), dict):
                                    msg = r["error"].get("message") or r["error"].get("stack")
                                if not msg and r.get("errors"):
                                    msg = r["errors"][0].get("message")
                                if msg:
                                    msgs.append(msg.strip())
                    if msgs:
                        fail["messages"] = msgs
                    failures.append(fail)
            for s in (node.get("suites") or []):
                walk(s)

        for top in (raw.get("suites") or []):
            walk(top)

        return {"total": total, "passed": expected, "failed": unexpected}, failures

    # 1) Explicit summary
    if isinstance(raw.get("summary"), dict):
        s = raw["summary"]
        total = int(s.get("total") or 0)
        passed = int(s.get("passed") or 0)
        failed = int(s.get("failed") or s.get("failures") or max(total - passed, 0))
        failures = raw.get("failures") or raw.get("failed") or raw.get("failedTests") or []
        return {"total": total, "passed": passed, "failed": failed}, failures

    # 2) Try flat tests/specs/results arrays
    tests = raw.get("tests") or raw.get("specs") or raw.get("results") or raw.get("cases") or []
    if isinstance(tests, list) and tests:
        def status_of(t):
            return (t.get("status") or t.get("outcome") or t.get("state") or t.get("result") or "").lower()
        total = len(tests)
        passed = sum(1 for t in tests if status_of(t) in {"passed", "ok", "success", "succeeded", "expected"})
        failed = sum(1 for t in tests if status_of(t) in {"failed", "fail", "broken", "error", "unexpected"})
        failures = raw.get("failures")
        if not isinstance(failures, list):
            failures = [t for t in tests if status_of(t) in {"failed", "fail", "broken", "error", "unexpected"}]
        return {"total": total, "passed": passed, "failed": failed}, failures

    # 3) Playwright-style nested suites (if stats missing)
    if isinstance(raw.get("suites"), list):
        total_specs = passed_specs = failed_specs = 0
        failures = []

        def spec_ok(spec):
            if spec.get("ok") is True: return True
            if spec.get("ok") is False: return False
            has_fail = False
            has_pass = False
            for t in (spec.get("tests") or []):
                for r in (t.get("results") or []):
                    st = (r.get("status") or "").lower()
                    if st == "passed": has_pass = True
                    if st == "failed": has_fail = True
            if has_fail: return False
            if has_pass: return True
            return False

        def walk(node):
            nonlocal total_specs, passed_specs, failed_specs
            for spec in (node.get("specs") or []):
                total_specs += 1
                ok = spec_ok(spec)
                if ok:
                    passed_specs += 1
                else:
                    failed_specs += 1
                    fail = {"title": spec.get("title"), "file": spec.get("file"), "line": spec.get("line")}
                    msgs = []
                    for t in (spec.get("tests") or []):
                        for r in (t.get("results") or []):
                            if (r.get("status") or "").lower() == "failed":
                                msg = None
                                if isinstance(r.get("error"), dict):
                                    msg = r["error"].get("message") or r["error"].get("stack")
                                if not msg and r.get("errors"):
                                    msg = r["errors"][0].get("message")
                                if msg:
                                    msgs.append(msg.strip())
                    if msgs:
                        fail["messages"] = msgs
                    failures.append(fail)
            for s in (node.get("suites") or []): walk(s)
        for top in raw["suites"]: walk(top)
        return {"total": total_specs, "passed": passed_specs, "failed": failed_specs}, failures

    # 4) Nothing matched → helpful error
    top_keys = ", ".join(sorted(raw.keys()))
    raise KeyError(f"Could not derive summary; top-level keys: {top_keys}")

# ---- tiny helper that prints the nice summary ----
def _print_pretty_summary(summary, failures):
    print("📊 Reading test results...")
    # If you later wire real LLM calls, detect env like OPENAI_API_KEY here
    print("🤖 Generating summary using AI...")  # or "(local rules)" if no API key
    print()
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    print("✅ Test Summary:")
    print(f"- {passed} of {total} tests passed successfully.")
    print(f"- {failed} failures detected.")
    # quick heuristics-based suggestions
    suggestions = set()
    for f in failures:
        msgs = f.get("messages") if isinstance(f, dict) else []
        text = "\n".join(msgs) if isinstance(msgs, list) else str(f)
        t = text.lower()
        if "timeout" in t and ("click" in t or "waiting for locator" in t):
            suggestions.add("Improve element wait logic (use locators + expect, increase timeouts, or waitForURL()).")
        if "tocontaintext" in t or "element(s) not found" in t or "locator(" in t:
            suggestions.add("Verify selectors and page state; ensure error containers render before asserting text.")
        if "auth" in t or "401" in t or "authentication" in t:
            suggestions.add("Check auth/API flows and test data seeding.")
    if suggestions:
        print("- Suggested next steps:")
        for s in sorted(suggestions):
            print(f"  • {s}")

def main(argv):
    # Accept path via argv[1] or REPORT_PATH env
    path = None
    if len(argv) > 1:
        path = argv[1]
    if not path:
        path = os.environ.get("REPORT_PATH")
    if not path:
        print("ERROR: Provide report path as arg or set REPORT_PATH.", file=sys.stderr)
        return 2

    p = pathlib.Path(path)
    if not p.is_file():
        print(f"ERROR: Report not found at: {p}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Could not parse JSON: {e}", file=sys.stderr)
        return 2

    try:
        summary, failures = _normalize_results(raw)
    except Exception as e:
        print(f"ERROR: Could not derive summary: {e}", file=sys.stderr)
        return 2

    _print_pretty_summary(summary, failures)
    # return non-zero if tests failed (so CI can fail on failures if you want)
    return 1 if summary.get("failed", 0) > 0 else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
