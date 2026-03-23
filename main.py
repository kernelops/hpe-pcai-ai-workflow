# main.py
import os
import glob
from common.models import DeploymentConfig
from agents.workflow_graph import run_graph


def test_with_langgraph(sample_log_path: str):
    """Run the full LangGraph pipeline against a single sample log."""

    config = DeploymentConfig(
        dag_id         = "pcai_deployment",
        node_ips       = ["10.0.0.1", "10.0.0.2"],
        os_version     = "ubuntu22.04",
        spp_version    = "2025.03",
        storage_config = {"minio_endpoint": "10.0.0.5:9000"}
    )

    print("\n" + "="*60)
    print("  HPE PCAI — LangGraph Pipeline")
    print(f"  Log: {os.path.basename(sample_log_path)}")
    print("="*60)

    final_state = run_graph(
        deployment_config = config,
        sample_log_path   = sample_log_path
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


def test_all_with_langgraph():
    """Test all sample logs through the LangGraph pipeline."""
    failed_logs = glob.glob("sample_logs/failed/*.log")
    print(f"\n🧪 Testing {len(failed_logs)} scenarios through LangGraph\n")

    for log_path in failed_logs:
        test_with_langgraph(log_path)
        print()


if __name__ == "__main__":
    test_all_with_langgraph()
