# integrations.py
import json
import urllib.request
from typing import Optional, Dict, Any

from utils import AppConfig


class SlackIntegration:
    """
    Minimal Slack webhook poster. Enabled when SLACK_WEBHOOK_URL is set.
    """

    def __init__(self, cfg: Optional[AppConfig] = None):
        self.cfg = cfg or AppConfig()
        self.webhook = self.cfg.slack_webhook_url

    def enabled(self) -> bool:
        return bool(self.webhook)

    def post_summary(self, title: str, analysis: Dict[str, Any]) -> Optional[int]:
        if not self.enabled():
            return None

        stats = analysis.get("stats", {})
        ci = analysis.get("ci", {})

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary*\n{analysis.get('summary','')}"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn",
                 "text": f"Tests: {stats.get('total',0)} | ✅ {stats.get('passed',0)} | ❌ {stats.get('failed',0)} | ⏭ {stats.get('skipped',0)} | 🔁 flaky {stats.get('flaky',0)}"}
            ]},
        ]

        # Show top patterns (if any)
        patterns = analysis.get("patterns", {}).get("top", [])
        if patterns:
            pat_lines = "\n".join([f"• *{sig}*: {count}" for sig, count in patterns[:5]])
            blocks += [
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Top patterns*\n{pat_lines}"}}
            ]

        if analysis.get("next_actions"):
            blocks += [
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Next actions*\n{analysis['next_actions']}"}}
            ]

        if ci.get("buildHref"):
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"CI Build: {ci['buildHref']}"}]
            })

        payload = {"blocks": blocks}
        req = urllib.request.Request(
            self.webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.getcode()
