# agents/run_workflow_agent.py
import requests
from datetime import datetime
from common.config import AIRFLOW_BASE_URL, AIRFLOW_USERNAME, AIRFLOW_PASSWORD
from common.models import DeploymentConfig

class RunWorkflowAgent:
    """
    Triggers the Airflow DAG with deployment config.
    Returns dag_run_id for Monitor Agent to track.
    """
    def __init__(self):
        self.base_url = AIRFLOW_BASE_URL
        self.auth = (AIRFLOW_USERNAME, AIRFLOW_PASSWORD)
        self.headers = {"Content-Type": "application/json"}

    def check_airflow_health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/v1/health",
                             auth=self.auth, timeout=5)
            return r.status_code == 200
        except Exception as e:
            print(f"[RunAgent] Airflow unreachable: {e}")
            return False

    def trigger_dag(self, config: DeploymentConfig, dag_id: str | None = None) -> str | None:
        target_dag_id = dag_id or config.dag_id
        print(f"[RunAgent] Triggering DAG: {target_dag_id}")

        if not self.check_airflow_health():
            print("[RunAgent] ❌ Airflow not reachable. Aborting.")
            return None

        payload = {
            "conf": {
                "node_ips":       config.node_ips,
                "os_version":     config.os_version,
                "spp_version":    config.spp_version,
                "storage_config": config.storage_config
            }
        }

        response = requests.post(
            f"{self.base_url}/api/v1/dags/{target_dag_id}/dagRuns",
            json=payload,
            auth=self.auth,
            headers=self.headers
        )

        if response.status_code == 200:
            dag_run_id = response.json()["dag_run_id"]
            print(f"[RunAgent] ✅ DAG triggered. Run ID: {dag_run_id}")
            return dag_run_id
        else:
            print(f"[RunAgent] ❌ Failed to trigger DAG: {response.text}")
            return None

    # ── MOCK for testing without real Airflow ─────────────────
    def trigger_dag_mock(self, config: DeploymentConfig, dag_id: str | None = None) -> str:
        target_dag_id = dag_id or config.dag_id
        run_id = f"manual__{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}"
        print(f"[RunAgent] 🧪 MOCK — DAG triggered ({target_dag_id}). Run ID: {run_id}")
        return run_id
