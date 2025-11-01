import os, re, json, sys, argparse

def send_to_slack(summary_text: str) -> None:
    """Send summarized failure report to Slack channel via webhook."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("⚠️  No SLACK_WEBHOOK_URL set — skipping Slack notification.")
        return
    payload = {"text": f"🧪 *Automation Test Summary*\n\n{summary_text}"}
    try:
        resp = requests.post(webhook_url, json=payload)
        if resp.status_code == 200:
            print("✅ Sent summary to Slack.")
        else:
            print(f"⚠️ Slack post failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️ Error posting to Slack: {e}")


def create_jira_ticket(title: str, description: str) -> None:
    """Create a Jira issue for critical/recurring failures."""
    base_url = os.environ.get("JIRA_BASE_URL")
    email = os.environ.get("JIRA_USER_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    project = os.environ.get("JIRA_PROJECT_KEY")

    if not all([base_url, email, token, project]):
        print("⚠️ Jira credentials missing — skipping ticket creation.")
        return

    url = f"{base_url}/rest/api/3/issue"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": title[:255],
            "description": description,
            "issuetype": {"name": "Bug"},
            "labels": ["automation-failure"],
        }
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=HTTPBasicAuth(email, token)
        )
        if response.status_code in (200, 201):
            issue_key = response.json().get("key")
            print(f"🐞 Jira ticket created: {issue_key}")
        else:
            print(f"⚠️ Jira creation failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Jira error: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="Path to Playwright JSON report")
    ap.add_argument("--mode", choices=["simple", "detailed"], default=os.environ.get("MODE", "simple"))
    ap.add_argument("--max-examples", type=int, default=int(os.environ.get("MAX_EXAMPLES", "2")))
    ap.add_argument("--strict-fails", action="store_true", default=os.environ.get("STRICT_FAILS", "false").lower() in {"1","true","yes"})
    args = ap.parse_args()

    print("📊 Reading test results...")
    with open(args.report, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    summary, failures = _normalize_results(raw)
    print("🤖 Generating summary using AI...\n")

    clusters = _cluster_failures(failures)

    if args.mode == "simple":
        out = _format_simple(summary, clusters, max_examples=args.max_examples)
    else:
        out = _format_simple(summary, clusters, max_examples=args.max_examples)

    print(out)
    _write_step_summary(out)

    # --- new integrations ---
    send_to_slack(out)

    if summary.get("failed", 0) > 0:
        top_cluster = clusters[0] if clusters else {}
        sig = top_cluster.get("sig", "")
        title = f"[Automation Failure] {sig[:80]}"
        description = f"{out}\n\nDetected in latest test run."
        create_jira_ticket(title, description)

    return 1 if (args.strict_fails and summary.get("failed", 0) > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
