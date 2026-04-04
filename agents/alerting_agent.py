# agents/alerting_agent.py
import json
import requests
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL, SLACK_WEBHOOK
from common.models import RootCauseReport, AlertResult

SEVERITY_EMOJI = {"critical": "🚨", "high": "⚠️", "low": "ℹ️"}

class AlertingAgent:
    """
    Uses LLM to compose a human-readable alert message.
    Routes to Slack/Email based on severity.
    """
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    def _compose_alert(self, rca: RootCauseReport) -> str:
        prompt = f"""Write a concise Slack alert for an HPE infrastructure engineer.

Deployment failure details:
- Task: {rca.error_report.task_id}
- Error: {rca.error_report.error_type}: {rca.error_report.error_message}
- Root Cause: {rca.root_cause}
- Classification: {rca.classification}
- Severity: {rca.severity.upper()}
- Required Action: {rca.engineer_action}

Rules:
- Start with severity emoji and [SEVERITY] tag
- Max 6 lines total
- Be specific and actionable
- No markdown headers, just plain text with emojis
- End with the exact action the engineer must take
- Do NOT repeat any line
- Each line must be unique and add new information
- Maximum 5 lines total"""

        if not self.client:
            emoji = SEVERITY_EMOJI.get(rca.severity, "⚠️")
            return (
                f"{emoji} [{rca.severity.upper()}] Deployment task {rca.error_report.task_id} failed\n"
                f"Error: {rca.error_report.error_type}: {rca.error_report.error_message}\n"
                f"Root cause: {rca.root_cause}\n"
                f"Action: {rca.engineer_action}"
            )

        response = self.client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()

    def _send_slack(self, message: str) -> bool:
        if not SLACK_WEBHOOK:
            print("[AlertingAgent] Slack webhook not configured — skipping")
            return False
        try:
            r = requests.post(SLACK_WEBHOOK,
                              json={"text": message}, timeout=5)
            return r.status_code == 200
        except Exception as e:
            print(f"[AlertingAgent] Slack send failed: {e}")
            return False

    def alert(self, rca: RootCauseReport) -> AlertResult:
        print(f"[AlertingAgent] 📣 Composing alert "
              f"(severity: {rca.severity})")

        alert_message  = self._compose_alert(rca)
        channels_notified = []

        if rca.severity in ["critical", "high"]:
            if self._send_slack(alert_message):
                channels_notified.append("slack")
                print(f"[AlertingAgent] ✅ Alert sent to Slack")
        else:
            print(f"[AlertingAgent] ℹ️  Low severity — logged only")

        # Always print to console
        emoji = SEVERITY_EMOJI.get(rca.severity, "⚠️")
        print(f"\n{'='*60}")
        print(f"ALERT:\n{alert_message}")
        print(f"{'='*60}\n")

        return AlertResult(
            alert_message     = alert_message,
            severity          = rca.severity,
            channels_notified = channels_notified
        )
