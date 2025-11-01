# main.py
import os, sys, json, argparse
from analyzer import _normalize_results, _cluster_failures, _format_simple
from integrations import create_jira_issue
from utils import write_step_summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="Path to Playwright JSON report")
    args = ap.parse_args()

    print("📊 Reading test results...")
    with open(args.report, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    summary, failures = _normalize_results(raw)
    clusters = _cluster_failures(failures)
    out = _format_simple(summary, clusters, max_examples=2)

    print(out)
    write_step_summary(out)

    send_to_slack(out)

    if summary.get("failed", 0) > 0:
        top_cluster = clusters[0] if clusters else {}
        sig = top_cluster.get("sig", "")
        title = f"[Automation Failure] {sig[:80]}"
        description = f"{out}\n\nDetected in latest test run."
        create_jira_ticket(title, description)

    return 1 if summary.get("failed", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
