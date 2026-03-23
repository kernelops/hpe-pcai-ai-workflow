# agents/root_cause_agent.py
import json
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL
from common.models import ErrorReport, RootCauseReport

VALID_CLASSIFICATIONS = {"transient", "config", "hardware", "version_mismatch"}
VALID_SEVERITIES      = {"critical", "high", "low"}

class RootCauseAgent:
    """
    Performs deep LLM reasoning to find the root cause,
    classify the error type, assign severity, and
    recommend one clear engineer action.
    """
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY)

    def analyse(self, error_report: ErrorReport) -> RootCauseReport:
        print(f"[RootCauseAgent] 🧠 Reasoning over: "
              f"{error_report.error_type}")

        prompt = f"""You are a senior HPE PCAI infrastructure expert performing 
root cause analysis on a deployment pipeline failure.

Task: {error_report.task_id}
Error Type: {error_report.error_type}
Error Message: {error_report.error_message}
Error Location: {error_report.error_line or 'unknown'}
Diagnosis: {error_report.diagnosis}

The deployment pipeline runs these tasks in order:
iLO Config → Switch Config → Deploy OS → Network Config → 
OS Validation → Deploy SPP → MinIO Install → MinIO Config → NFS Config

Perform root cause analysis and respond with ONLY valid JSON:
{{
    "root_cause": "single clear sentence explaining the underlying root cause",
    "classification": "one of: transient / config / hardware / version_mismatch",
    "severity": "one of: critical / high / low",
    "engineer_action": "one actionable sentence — exactly what the engineer must do"
}}

Classification guide:
- transient: network blip, timeout, PXE boot failure, DHCP no response, NFS mount timeout — retry will likely fix
- config: wrong credentials, wrong version, misconfiguration, missing package or dependency
- hardware: physical node unreachable, disk failure, NIC issue, SSH 'no route to host'
- version_mismatch: incompatible OS/SPP/MinIO/firmware versions

Severity guide:
- critical: blocks entire deployment, data loss risk, hardware issue
- high: deployment stopped, needs immediate engineer attention
- low: warning only, auto-retry likely to succeed"""

        response = self.client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        parsed = json.loads(raw.strip())

        # Validate classification and severity
        classification = parsed["classification"].lower()
        severity       = parsed["severity"].lower()

        if classification not in VALID_CLASSIFICATIONS:
            classification = "config"
        if severity not in VALID_SEVERITIES:
            severity = "high"

        report = RootCauseReport(
            error_report     = error_report,
            root_cause       = parsed["root_cause"],
            classification   = classification,
            severity         = severity,
            engineer_action  = parsed["engineer_action"]
        )

        print(f"[RootCauseAgent] ✅ Root cause: {report.classification} | "
              f"Severity: {report.severity}")
        return report
