# demo_pipeline.py
# Run: python demo_pipeline.py

from agents.log_analyser_agent     import LogAnalyserAgent
from agents.root_cause_agent       import RootCauseAgent
from agents.alerting_agent         import AlertingAgent
from common.models                 import TaskFailure

SCENARIOS = [
    {
        "name"    : "🪣  Scenario 1 — MinIO Service Error",
        "task_id" : "simulate_minio_service_error",
        "log_path": "sample_logs/failed/minio_service_error.log",
        "dag_id"  : "deployment_workflow",
        "run_id"  : "manual__2026-03-23T13:51:55"
    },
    {
        "name"    : "📁  Scenario 2 — NFS Configuration Error",
        "task_id" : "simulate_nfs_configuration_error",
        "log_path": "sample_logs/failed/nfs_configuration_error.log",
        "dag_id"  : "deployment_workflow",
        "run_id"  : "manual__2026-03-23T13:51:55"
    },
    {
        "name"    : "🖥️  Scenario 3 — OS Validation Error",
        "task_id" : "simulate_os_validation_error",
        "log_path": "sample_logs/failed/os_validation_error.log",
        "dag_id"  : "deployment_workflow",
        "run_id"  : "manual__2026-03-23T13:51:55"
    },
]

_log   = LogAnalyserAgent()
_rca   = RootCauseAgent()
_alert = AlertingAgent()

SEP = "=" * 65

def run_scenario(scenario):
    failure = TaskFailure(
        task_id    = scenario["task_id"],
        dag_id     = scenario["dag_id"],
        run_id     = scenario["run_id"],
        state      = "failed",
        log_path   = scenario["log_path"]
    )

    print(f"\n{SEP}")
    print(f"  {scenario['name']}")
    print(SEP)

    # ── Agent 1: Workflow + Monitor (static — failure already known) ──────
    print("\n🔵  WORKFLOW AGENT")
    print(f"   DAG        : {scenario['dag_id']}")
    print(f"   Run ID     : {scenario['run_id']}")
    print(f"   Failed Task: {scenario['task_id']}")
    print(f"   Status     : ❌ FAILED")

    # ── Agent 2: Log Analysis ─────────────────────────────────────────────
    print("\n🟠  LOG ANALYSIS AGENT")
    error_report = _log.analyse(failure)
    for step in [
        f"Fetched log for task: {failure.task_id}",
        "Chunking and tokenising log content...",
        "Querying RAG layer for similar HPE error patterns...",
        f"Error type identified : {error_report.error_type}",
        f"Confidence           : {int(error_report.confidence * 100)}%",
    ]:
        print(f"   → {step}")
    print(f"\n   Error        : {error_report.error_message}")
    print(f"   Location     : {error_report.error_line}")
    print(f"   Diagnosis    : {error_report.diagnosis}")

    # ── Agent 3: Root Cause ───────────────────────────────────────────────
    print("\n🟡  ROOT CAUSE AGENT")
    rca = _rca.analyse(error_report)
    for step in [
        f"Received error report : {error_report.error_type}",
        "Reasoning over cause chain with LLM...",
        f"Classification : {rca.classification}",
        f"Severity       : {rca.severity.upper()}",
    ]:
        print(f"   → {step}")
    print(f"\n   Root Cause : {rca.root_cause}")
    print(f"   Action     : {rca.engineer_action}")

    # ── Agent 4: Alerting ─────────────────────────────────────────────────
    print("\n🔴  ALERTING AGENT")
    alert = _alert.alert(rca)
    is_critical = rca.severity.lower() == "critical"
    for step in [
        f"Severity assessed : {rca.severity.upper()}",
        "Composing human-readable alert...",
        f"Action status : {'⚠️  REVIEW NEEDED' if is_critical else '✅ SAFE TO ACTION'}",
        f"Routing via   : {', '.join(alert.channels_notified or ['console'])}",
    ]:
        print(f"   → {step}")
    print(f"\n   Alert:\n   {alert.alert_message}")

    # ── Combined Summary ──────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("📋  COMBINED SUMMARY")
    print(f"   Verdict    : 🚨 [{rca.severity.upper()}] Deployment failed at {failure.task_id}")
    print(f"   Error      : {error_report.error_type} — {error_report.error_message}")
    print(f"   Root Cause : {rca.root_cause}")
    print(f"   Fix        : {rca.engineer_action}")
    print(f"   Approval   : {'Required ⚠️' if is_critical else 'Not required ✅'}")
    print(f"{'─' * 65}\n")


if __name__ == "__main__":
    print("\n🚀  HPE PCAI — AI Agent Pipeline Demo")
    print("     Running 3 failure scenarios...\n")
    for scenario in SCENARIOS:
        run_scenario(scenario)
    print("\n✅  Demo complete.\n")