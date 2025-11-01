# integrations.py
import os
import requests
from requests.auth import HTTPBasicAuth


def send_to_slack(summary_text: str) -> None:
    """Send summarized failure report to Slack channel via webhook."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("⚠️ No SLACK_WEBHOOK_URL set — skipping Slack notification.")
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
    """Create a Jira issue for recurring or critical failures."""
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
        response = requests.post(url, json=payload, headers=headers, auth=HTTPBasicAuth(email, token))
        if response.status_code in (200, 201):
            issue_key = response.json().get("key")
            print(f"🐞 Jira ticket created: {issue_key}")
        else:
            print(f"⚠️ Jira creation failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Jira error: {e}")
