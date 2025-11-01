# main.py
import os, sys, json, argparse
import json
from analyzer import _normalize_results, _cluster_failures, _format_simple
from integrations import create_jira_issue,send_to_slack
from utils import write_step_summary


def extract_specs(suite):
    """Recursively extract specs from nested Playwright suites."""
    results = []
    if "specs" in suite:
        results.extend(suite["specs"])
    if "suites" in suite:
        for s in suite["suites"]:
            results.extend(extract_specs(s))
    return results

def get_error_message(test):
    """Safely extract error message from nested test JSON."""
    try:
        tests = test.get("tests", [])
        if tests and "errors" in tests[0] and len(tests[0]["errors"]) > 0:
            return tests[0]["errors"][0].get("message", "No message")
    except Exception:
        pass
    return "Unknown error"

def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/sample_results.json"
    print("📊 Reading test results...")

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract all specs recursively
    all_specs = []
    for suite in data.get("suites", []):
        all_specs.extend(extract_specs(suite))

    total = len(all_specs)
    passed = len([t for t in all_specs if t.get("ok")])
    failed = total - passed

    top_issues = []
    for test in all_specs:
        if not test.get("ok"):
            error_msg = get_error_message(test)
            top_issues.append({
                "error": error_msg,
                "examples": [test["title"]]
            })


    out = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "top_issues": top_issues[:3]  # limit to top 3
    }

    print(f"✅ {passed}/{total} passed • {failed} failed")

    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if webhook_url:
        send_to_slack(out, webhook_url)
    else:
        print("⚠️ SLACK_WEBHOOK_URL not found, skipping Slack notification")
        
     # 🐞 Create Jira ticket if failures exist
    if failed > 0:
        env = {
            "JIRA_BASE_URL": os.getenv("JIRA_BASE_URL"),
            "JIRA_USER_EMAIL": os.getenv("JIRA_USER_EMAIL"),
            "JIRA_API_TOKEN": os.getenv("JIRA_API_TOKEN"),
            "JIRA_PROJECT_KEY": os.getenv("JIRA_PROJECT_KEY")
        }

        if all(env.values()):
            summary = f"[TestInsight] {failed}/{total} Tests Failed in Playwright Run"
            desc_lines = [f"Total Tests: {total}", f"Passed: {passed}", f"Failed: {failed}", "", "Top Issues:"]
            for issue in out["top_issues"]:
                desc_lines.append(f"- {issue['error']} ({', '.join(issue['examples'])})")
            description = "\n".join(desc_lines)
            create_jira_issue(summary, description, env)
        else:
            print("⚠️ Jira credentials missing — skipping Jira ticket creation.")


if __name__ == "__main__":
    sys.exit(main())
