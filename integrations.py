from typing import Dict
import requests
import json
from requests.auth import HTTPBasicAuth

def send_to_slack(summary: dict, webhook_url: str):
    """Send formatted summary to Slack."""
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    total = summary.get("total", 0)
    top_issues = summary.get("top_issues", [])

    # Header and summary section
    text_blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🧪 Test Results Summary"}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{passed}/{total} passed* • *{failed} failed*"
            }
        },
    ]

    # Add top issues if any
    if top_issues:
        issues_text = ""
        for i, issue in enumerate(top_issues, start=1):
            issues_text += f"*{i})* `{issue['error']}`\n"
            if "examples" in issue:
                for ex in issue["examples"]:
                    issues_text += f"   • `{ex}`\n"
            issues_text += "\n"

        text_blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Top Issues:*\n{issues_text.strip()}"
                }
            }
        )

    # Add divider and footer
    text_blocks.append({"type": "divider"})
    text_blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "📅 Sent automatically by *TestInsight Agent*"}]
    })

    # Send message
    payload = {"blocks": text_blocks}
    resp = requests.post(webhook_url, data=json.dumps(payload), headers={"Content-Type": "application/json"})

    if resp.status_code == 200:
        print("✅ Sent formatted report to Slack")
    else:
        print(f"⚠️ Failed to send Slack message: {resp.status_code} {resp.text}")

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
