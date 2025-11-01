# main.py
import os, sys, json, argparse
import json
from analyzer import _normalize_results, _cluster_failures, _format_simple
from integrations import create_jira_issue,send_to_slack
from utils import write_step_summary


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/sample_results.json"
    print("📊 Reading test results...")

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data["suites"][0]["specs"])
    passed = len([t for t in data["suites"][0]["specs"] if t["ok"]])
    failed = total - passed

    top_issues = []
    for test in data["suites"][0]["specs"]:
        if not test["ok"]:
            top_issues.append({
                "error": test.get("error", "Unknown error"),
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


if __name__ == "__main__":
    sys.exit(main())
