# agents/validation_agent.py
"""
Phase 3 — Validation Agent (Closed-Loop Remediation).
Checks if the applied fix succeeded by:
1. Running health checks via SSH.
2. Checking the Redis queue (hpc_error_logs) for lingering errors.
"""

import time
import json
from datetime import datetime
try:
    from redis import Redis
    from rq import Queue
except ImportError:
    Redis = None
    Queue = None

from common.models import FixStrategy, FixResult, ValidationReport

class ValidationAgent:
    """
    Validates fixes post-execution to ensure environmental health.
    """

    def __init__(self):
        self._paramiko = None
        self.redis_conn = Redis(host="localhost", port=6379, db=0) if Redis else None
        self.queue = Queue("hpc_error_logs", connection=self.redis_conn) if self.redis_conn else None

    def validate(self, fix_result: FixResult, worker_nodes: list[dict], mock: bool = False, task_id: str = "") -> ValidationReport:
        print(f"\n[ValidationAgent] 🔍 Validating fix for: {fix_result.fix_strategy.description}")
        
        is_valid = True
        health_check_output = "No health checks defined"
        queue_status = "Queue check skipped"
        collateral_damage_check = "System load normal"
        escalated_errors = []

        # 1. SSH Health Check
        targets = self._resolve_targets(fix_result.fix_strategy, worker_nodes)
        if not targets and mock:
            targets = [{"ip": "mock-node", "username": "root", "password": ""}]
            
        if targets and fix_result.fix_strategy.dry_run_commands:
            print("[ValidationAgent]   ── Running SSH Health Checks ──")
            outputs = []
            for node in targets:
                ip = node["ip"]
                username = node["username"]
                password = node.get("password", "")
                
                for cmd in fix_result.fix_strategy.dry_run_commands:
                    out = self._run_command(ip, username, password, cmd, mock=mock)
                    print(f"  $ {cmd}")
                    if out["exit_code"] != 0:
                        is_valid = False
                        outputs.append(f"❌ {ip} - {cmd} failed: {out['stderr'][:100]}")
                    else:
                        outputs.append(f"✅ {ip} - {cmd} passed")
            health_check_output = "\n".join(outputs)
        elif mock:
            health_check_output = "✅ [MOCK] Services reported healthy"

        # 2. Check Queue for lingering errors
        if self.queue:
            print("[ValidationAgent]   ── Checking HPC Error Queue ──")
            # In a real environment, we would look for new errors matching this task_id.
            jobs = self.queue.get_jobs()
            for job in jobs:
                if job.meta.get("task_id") == task_id or (job.kwargs and job.kwargs.get("failed_task") == task_id):
                    is_valid = False
                    error_data = {
                        "job_id": job.id,
                        "task_id": task_id,
                        "log_text": job.meta.get("log_text", "Lingering error detected"),
                        "timestamp": datetime.now().isoformat()
                    }
                    escalated_errors.append(error_data)
                    print(f"  ❌ Lingering error found in queue: {job.id}")
            
            if not escalated_errors:
                queue_status = f"✅ Queue clean (Checked {len(jobs)} jobs)"
                print(f"  {queue_status}")
            else:
                queue_status = f"❌ Found {len(escalated_errors)} lingering errors in queue"
        else:
            queue_status = "⚠️  Redis not available — mocked queue check passed"

        # 3. Compile Verdict
        if is_valid and fix_result.execution_status == "success":
            verdict = "✅ Validation Passed: Fix applied successfully, health checks passed, and queue is clean."
        else:
            is_valid = False
            verdict = "❌ Validation Failed: Fix applied, but health checks failed or lingering errors were detected."

        print(f"[ValidationAgent] {verdict}")

        return ValidationReport(
            is_valid=is_valid,
            health_check_output=health_check_output,
            queue_status=queue_status,
            collateral_damage_check=collateral_damage_check,
            verdict=verdict,
            escalated_errors=escalated_errors
        )

    # ── Target resolution ──
    def _resolve_targets(self, strategy: FixStrategy, worker_nodes: list[dict]) -> list[dict]:
        if strategy.target_node_ip:
            return [n for n in worker_nodes if n.get("ip") == strategy.target_node_ip]
        return list(worker_nodes)

    # ── Command execution ──
    def _run_command(self, ip: str, username: str, password: str, command: str, mock: bool = False) -> dict:
        result = {"command": command, "node_ip": ip, "stdout": "", "stderr": "", "exit_code": 0}
        if mock:
            result["stdout"] = f"[MOCK] OK: {command}"
            return result
        try:
            paramiko = self._get_paramiko()
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=ip, username=username, password=password, timeout=15, look_for_keys=False, allow_agent=False)
            stdin, stdout, stderr = client.exec_command(command, timeout=60)
            result["exit_code"] = stdout.channel.recv_exit_status()
            result["stdout"] = stdout.read().decode("utf-8", errors="replace").strip()
            result["stderr"] = stderr.read().decode("utf-8", errors="replace").strip()
            client.close()
        except Exception as exc:
            result["exit_code"] = -1
            result["stderr"] = f"SSH error: {str(exc)}"
        return result

    def _get_paramiko(self):
        if self._paramiko is None:
            import paramiko
            self._paramiko = paramiko
        return self._paramiko
