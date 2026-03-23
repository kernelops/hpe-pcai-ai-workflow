# agents/monitor_workflow_agent.py
import requests
import time
import os
from datetime import datetime
from common.config import (AIRFLOW_BASE_URL, AIRFLOW_USERNAME,
                           AIRFLOW_PASSWORD, POLL_INTERVAL_SEC,
                           TASK_TIMEOUT_SEC, AIRFLOW_DAG_ID)
from common.models import TaskFailure

TERMINAL_STATES  = {"success", "failed", "upstream_failed", "skipped"}
FAILURE_STATES   = {"failed", "upstream_failed"}

class MonitorWorkflowAgent:
    """
    Polls Airflow task states. On failure, fetches the log
    and returns a TaskFailure object for the Log Analyser Agent.
    """
    def __init__(self):
        self.base_url = AIRFLOW_BASE_URL
        self.auth     = (AIRFLOW_USERNAME, AIRFLOW_PASSWORD)

    def get_task_instances(self, dag_run_id: str) -> list[dict]:
        r = requests.get(
            f"{self.base_url}/api/v1/dags/{AIRFLOW_DAG_ID}"
            f"/dagRuns/{dag_run_id}/taskInstances",
            auth=self.auth
        )
        return r.json().get("task_instances", [])

    def get_task_log(self, dag_run_id: str, task_id: str) -> str:
        r = requests.get(
            f"{self.base_url}/api/v1/dags/{AIRFLOW_DAG_ID}"
            f"/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/1",
            auth=self.auth
        )
        return r.text if r.status_code == 200 else "Log unavailable"

    def monitor(self, dag_run_id: str) -> TaskFailure | None:
        """
        Polls until DAG completes or a task fails.
        Returns TaskFailure if something fails, None if all succeed.
        """
        print(f"[MonitorAgent] 👁 Watching DAG run: {dag_run_id}")
        task_start_times = {}

        while True:
            tasks = self.get_task_instances(dag_run_id)

            for task in tasks:
                task_id = task["task_id"]
                state   = task["state"]

                # Track when task started running
                if state == "running" and task_id not in task_start_times:
                    task_start_times[task_id] = time.time()

                # Detect stall (running too long)
                if state == "running" and task_id in task_start_times:
                    elapsed = time.time() - task_start_times[task_id]
                    if elapsed > TASK_TIMEOUT_SEC:
                        print(f"[MonitorAgent] ⚠️  Task STALLED: {task_id} "
                              f"({int(elapsed)}s)")
                        log = self.get_task_log(dag_run_id, task_id)
                        return TaskFailure(
                            dag_run_id=dag_run_id,
                            task_id=task_id,
                            state="stalled",
                            log_text=log,
                            timestamp=datetime.now().isoformat()
                        )

                # Detect actual failure
                if state in FAILURE_STATES:
                    print(f"[MonitorAgent] ❌ Task FAILED: {task_id} "
                          f"(state: {state})")
                    log = self.get_task_log(dag_run_id, task_id)
                    return TaskFailure(
                        dag_run_id=dag_run_id,
                        task_id=task_id,
                        state=state,
                        log_text=log,
                        timestamp=datetime.now().isoformat()
                    )

            # Check if all tasks reached terminal state
            all_done = all(t["state"] in TERMINAL_STATES for t in tasks)
            if all_done:
                print("[MonitorAgent] ✅ All tasks completed successfully.")
                return None

            print(f"[MonitorAgent] ⏳ Polling... "
                  f"({len(tasks)} tasks tracked)")
            time.sleep(POLL_INTERVAL_SEC)

    # MOCK for testing with sample logs 
# agents/monitor_workflow_agent.py — replace monitor_mock() with this:
    def monitor_mock(self, dag_run_id: str, sample_log_path: str) -> TaskFailure:
        with open(sample_log_path, "r") as f:
            log_text = f.read()

        # Derive task_id from filename — e.g. "configure_storage_failed.log" → "configure_storage"
        filename = os.path.basename(sample_log_path)
        task_id  = filename.replace("_failed.log", "").replace("_success.log", "")

        print(f"[MonitorAgent] 🧪 MOCK — Simulating task failure for: {task_id}")
        return TaskFailure(
            dag_run_id = dag_run_id,
            task_id    = task_id,
            state      = "failed",
            log_text   = log_text,
            timestamp  = datetime.now().isoformat()
        )

