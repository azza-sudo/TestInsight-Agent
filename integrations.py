from typing import Dict
import requests
from requests.auth import HTTPBasicAuth

def send_to_slack(summary: str, webhook_url: str) -> None:
    """Send test summary to Slack via Incoming Webhook."""
    if not webhook_url:
        print("⚠️ No SLACK_WEBHOOK_URL set — skipping Slack notification.")
        return

    payload = {"text": summary}
    try:
        resp = requests.post(webhook_url, json=payload)
        if resp.status_code == 200:
            print("✅ Slack notification sent.")
        else:
            print(f"⚠️ Slack notification failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️ Slack error: {e}")

def create_jira_issue(summary: str, description: str, env: Dict[str, str]) -> None:
    base_url = env.get("JIRA_BASE_URL")
    email = env.get("JIRA_USER_EMAIL")
    token = env.get("JIRA_API_TOKEN")
    project_key = env.get("JIRA_PROJECT_KEY")

    if not all([base_url, email, token, project_key]):
        print("⚠️ Jira credentials missing — skipping ticket creation.")
        return

    url = f"{base_url}/rest/api/3/issue"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = HTTPBasicAuth(email, token)

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}]
                    }
                ]
            },
            "issuetype": {"name": "Bug"},
        }
    }

    resp = requests.post(url, headers=headers, auth=auth, json=payload)
    if resp.status_code == 201:
        print(f"✅ Jira issue created: {resp.json().get('key')}")
    else:
        print(f"⚠️ Jira creation failed: {resp.status_code} {resp.text}")
