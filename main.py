# main.py
import os
import sys
import glob
from common.models import DeploymentConfig
from agents.workflow_graph import run_graph


def test_with_langgraph(sample_log_path: str, autofix: bool = False):
    """Run the full LangGraph pipeline against a single sample log."""

    config = DeploymentConfig(
        dag_id         = "pcai_deployment",
        node_ips       = ["10.0.0.1", "10.0.0.2"],
        os_version     = "ubuntu22.04",
        spp_version    = "2025.03",
        storage_config = {"minio_endpoint": "10.0.0.5:9000"}
    )

    # Mock worker nodes for autofix SSH simulation
    worker_nodes = [
        {"ip": "10.0.0.1", "username": "root", "password": "password"},
        {"ip": "10.0.0.2", "username": "root", "password": "password"},
    ] if autofix else []

    print("\n" + "="*60)
    print(f"  HPE PCAI — LangGraph Pipeline {'+ Autofix' if autofix else ''}")
    print(f"  Log: {os.path.basename(sample_log_path)}")
    print("="*60)

    final_state = run_graph(
        deployment_config = config,
        sample_log_path   = sample_log_path,
        autofix_enabled   = autofix,
        worker_nodes      = worker_nodes,
        max_retries       = 2,
    )

    print("\n📋 Final State Summary:")
    print(f"  Status      : {final_state['pipeline_status'].upper()}")
    if final_state["error_report"]:
        print(f"  Error Type  : {final_state['error_report'].error_type}")
    if final_state["rca_report"]:
        print(f"  Root Cause  : {final_state['rca_report'].root_cause}")
        print(f"  Severity    : {final_state['rca_report'].severity.upper()}")
    if final_state["alert_result"]:
        print(f"  Notified    : {final_state['alert_result'].channels_notified or ['console']}")

    # Phase 2: Show autofix results
    if final_state.get("fix_strategy"):
        strategy = final_state["fix_strategy"]
        print(f"\n🔧 Fix Strategy:")
        print(f"  Type        : {strategy.fix_type}")
        print(f"  Risk        : {strategy.estimated_risk}")
        print(f"  Description : {strategy.description}")
        print(f"  Commands    : {len(strategy.fix_commands)}")
        for i, cmd in enumerate(strategy.fix_commands, 1):
            print(f"    {i}. {cmd}")
    if final_state.get("fix_result"):
        result = final_state["fix_result"]
        print(f"\n⚡ Fix Execution:")
        print(f"  Status      : {result.execution_status.upper()}")
        if result.error_on_fix:
            print(f"  Error       : {result.error_on_fix}")
        print(f"  Outputs     : {len(result.command_outputs)} command(s)")


def test_all_with_langgraph(autofix: bool = False):
    """Test all sample logs through the LangGraph pipeline."""
    failed_logs = glob.glob("sample_logs/failed/*.log")
    label = "with Autofix" if autofix else "Phase 1 only"
    print(f"\n🧪 Testing {len(failed_logs)} scenarios through LangGraph ({label})\n")

    for log_path in failed_logs:
        test_with_langgraph(log_path, autofix=autofix)
        print()


if __name__ == "__main__":
    autofix = "--autofix" in sys.argv
    test_all_with_langgraph(autofix=autofix)

