# agents/dag_patch_agent.py
"""
Phase 2 Hybrid — DAG Patch Agent.
Writes the corrected DAG source as remediation_workflow.py,
triggers it via the Airflow REST API, and monitors the run outcome.
"""

import os
import time
import requests
from datetime import datetime
from common.models import DagPatchResult, DagAnalysisReport

DAGS_DIR = os.path.join(os.path.dirname(__file__), "..", "airflow", "dags")
AIRFLOW_API = os.getenv("AIRFLOW_API_URL", "http://localhost:8080/api/v1")
AIRFLOW_USER = os.getenv("AIRFLOW_USER", "airflow")
AIRFLOW_PASS = os.getenv("AIRFLOW_PASS", "airflow")


class DagPatchAgent:
    """
    Writes corrected DAG source to airflow/dags/ and triggers
    the remediation run via the Airflow REST API.
    """

    REMEDIATION_DAG_ID = "remediation_workflow"
    POLL_INTERVAL = 5        # seconds between status checks
    MAX_WAIT      = 120      # total seconds to wait for DAG completion

    # ── Public entry point ────────────────────────────────────

    def patch_and_run(self, analysis: DagAnalysisReport,
                      attempt_number: int = 1,
                      worker_nodes: list[dict] | None = None) -> DagPatchResult:
        """Write the corrected DAG, trigger it, and monitor the outcome."""
        print(f"\n[DagPatch] 📝 Attempt {attempt_number} — Writing remediation DAG")

        if not analysis.corrected_source:
            print("[DagPatch] ⚠️  No corrected source provided — cannot patch")
            return DagPatchResult(
                dag_written=False,
                attempt_number=attempt_number,
                run_outcome="failed",
            )

        # 1. Write the corrected DAG file
        written = self._write_dag(analysis.corrected_source)
        if not written:
            return DagPatchResult(
                dag_written=False,
                attempt_number=attempt_number,
                run_outcome="failed",
            )

        # 2. Wait for Airflow to detect the new DAG (actively poll)
        if not self._wait_for_dag_available():
            print("[DagPatch]   ❌ Airflow did not detect the DAG in time")
            return DagPatchResult(
                dag_written=True,
                attempt_number=attempt_number,
                run_outcome="failed",
            )

        # 3. Unpause the DAG (it may be paused on first creation)
        self._unpause_dag()

        # 4. Trigger the DAG run via API
        conf = {}
        if worker_nodes:
            conf["worker_nodes"] = worker_nodes

        dag_run_id = self._trigger_dag(conf)
        if not dag_run_id:
            return DagPatchResult(
                dag_written=True,
                attempt_number=attempt_number,
                run_outcome="failed",
            )

        # 5. Poll for completion
        outcome, failed_tasks = self._poll_dag_run(dag_run_id)

        print(f"[DagPatch] {'✅' if outcome == 'success' else '❌'} "
              f"Attempt {attempt_number} outcome: {outcome}")
        if failed_tasks:
            print(f"[DagPatch]   Failed tasks: {', '.join(failed_tasks)}")

        return DagPatchResult(
            dag_written=True,
            remediation_dag_id=self.REMEDIATION_DAG_ID,
            dag_run_id=dag_run_id,
            run_outcome=outcome,
            attempt_number=attempt_number,
            failed_tasks=failed_tasks,
        )

    # ── DAG file writing ──────────────────────────────────────

    def _write_dag(self, source: str) -> bool:
        """Write the corrected Python source to the dags directory."""
        path = os.path.join(DAGS_DIR, "remediation_workflow.py")
        try:
            with open(path, "w") as f:
                f.write(source)
            print(f"[DagPatch]   ✅ Wrote {path}")
            return True
        except Exception as exc:
            print(f"[DagPatch]   ❌ Failed to write DAG: {exc}")
            return False

    # ── Airflow REST API helpers ──────────────────────────────

    def _auth(self) -> tuple[str, str]:
        return (AIRFLOW_USER, AIRFLOW_PASS)

    def _wait_for_dag_available(self) -> bool:
        """Poll Airflow API until the DAG is visible, or time out after 60s."""
        url = f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}"
        max_wait = 60
        elapsed = 0
        interval = 3

        print(f"[DagPatch]   ⏳ Waiting for Airflow to detect the DAG (max {max_wait}s)...")

        # First, try to force a DAG reparse
        self._force_dag_reparse()

        while elapsed < max_wait:
            try:
                resp = requests.get(url, auth=self._auth(), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get("has_import_errors", False):
                        print(f"[DagPatch]   ✅ DAG detected by Airflow ({elapsed}s)")
                        return True
                    else:
                        print(f"[DagPatch]   ⚠️  DAG detected but has import errors!")
                        return False
                elif resp.status_code == 404:
                    print(f"[DagPatch]   ... DAG not yet visible ({elapsed}s)")
                else:
                    print(f"[DagPatch]   ... unexpected status {resp.status_code} ({elapsed}s)")
            except Exception as exc:
                print(f"[DagPatch]   ... API check failed: {exc}")

            time.sleep(interval)
            elapsed += interval

        print(f"[DagPatch]   ⚠️  Timed out waiting for DAG detection ({max_wait}s)")
        return False

    def _force_dag_reparse(self):
        """Ask Airflow to reparse DAGs by sending a PATCH to force serialization."""
        try:
            # Trigger the scheduler to pick up the new file immediately
            # by doing a PATCH on the dags endpoint (even if it 404s, it wakes up parsing)
            url = f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}"
            requests.patch(
                url,
                json={"is_paused": False},
                auth=self._auth(),
                timeout=5,
            )
        except Exception:
            pass  # Expected to fail on first creation; that's fine

    def _unpause_dag(self):
        """Unpause the remediation DAG so it can be triggered."""
        url = f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}"
        try:
            resp = requests.patch(
                url,
                json={"is_paused": False},
                auth=self._auth(),
                timeout=10,
            )
            if resp.status_code == 200:
                print("[DagPatch]   ✅ DAG unpaused")
            else:
                print(f"[DagPatch]   ⚠️  Unpause returned {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            print(f"[DagPatch]   ⚠️  Unpause request failed: {exc}")

    def _trigger_dag(self, conf: dict | None = None) -> str | None:
        """Trigger a new DAG run via the Airflow REST API."""
        url = f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}/dagRuns"
        run_id = f"autofix_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        payload = {
            "dag_run_id": run_id,
            "conf": conf or {},
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                auth=self._auth(),
                timeout=15,
            )
            if resp.status_code in (200, 201):
                actual_id = resp.json().get("dag_run_id", run_id)
                print(f"[DagPatch]   ✅ Triggered DAG run: {actual_id}")
                return actual_id
            else:
                print(f"[DagPatch]   ❌ Trigger failed ({resp.status_code}): {resp.text[:200]}")
                return None
        except Exception as exc:
            print(f"[DagPatch]   ❌ Trigger request failed: {exc}")
            return None

    def _poll_dag_run(self, dag_run_id: str) -> tuple[str, list[str]]:
        """Poll the DAG run status until it completes or times out."""
        url = f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}/dagRuns/{dag_run_id}"
        elapsed = 0

        print(f"[DagPatch]   ⏳ Polling DAG run status (max {self.MAX_WAIT}s)...")
        while elapsed < self.MAX_WAIT:
            time.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL

            try:
                resp = requests.get(url, auth=self._auth(), timeout=10)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                state = data.get("state", "")

                if state in ("success", "failed"):
                    failed = self._get_failed_tasks(dag_run_id)
                    if failed:
                        return ("failed", failed)
                    return ("success", [])
                else:
                    print(f"[DagPatch]   ... state={state} ({elapsed}s elapsed)")
            except Exception:
                pass

        print(f"[DagPatch]   ⚠️  Timed out after {self.MAX_WAIT}s")
        return ("timeout", [])

    def _get_failed_tasks(self, dag_run_id: str) -> list[str]:
        """Retrieve the list of failed task IDs from a DAG run."""
        url = (f"{AIRFLOW_API}/dags/{self.REMEDIATION_DAG_ID}"
               f"/dagRuns/{dag_run_id}/taskInstances")
        try:
            resp = requests.get(url, auth=self._auth(), timeout=10)
            if resp.status_code == 200:
                tasks = resp.json().get("task_instances", [])
                return [t["task_id"] for t in tasks
                        if t.get("state") in ("failed", "upstream_failed")]
        except Exception:
            pass
        return []
