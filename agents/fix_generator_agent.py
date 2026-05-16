# agents/fix_generator_agent.py
"""
Phase 2 — Fix Generator Agent.
Takes a RootCauseReport and produces a concrete FixStrategy
with SSH commands to remediate the failure.

Two resolution paths:
1. Deterministic fix registry — for known simulated error patterns (high reliability).
2. LLM-generated fixes — for unknown errors (uses RAG solution as guidance).
"""

import json
import re
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL
from common.models import RootCauseReport, FixStrategy


# ── Deterministic fix registry ────────────────────────────────
# Maps task_id patterns to pre-built fix strategies for the
# simulated errors in deployment_workflow.py.

FIX_REGISTRY: dict[str, FixStrategy] = {
    "simulate_os_validation_error": FixStrategy(
        fix_type="config_correction",
        fix_commands=[
            "sudo touch /etc/redhat-release",
            "echo 'Red Hat Enterprise Linux release 8.8 (Ootpa)' | sudo tee /etc/redhat-release",
        ],
        dry_run_commands=["cat /etc/os-release"],
        requires_approval=False,
        estimated_risk="low",
        description=(
            "Create /etc/redhat-release with appropriate content to "
            "satisfy the OS baseline validation check."
        ),
    ),
    "simulate_nfs_configuration_error": FixStrategy(
        fix_type="config_correction",
        fix_commands=[
            "sudo apt-get update && sudo apt-get install -y nfs-kernel-server || true",
            "printf '%s\\n' '/srv/nfs/share *(rw,sync,no_subtree_check)' | sudo tee /etc/exports > /dev/null",
            "sudo exportfs -ra",
        ],
        dry_run_commands=["cat /etc/exports", "sudo exportfs -v"],
        requires_approval=False,
        estimated_risk="low",
        description=(
            "Replace the broken NFS export option (broken_option) with valid "
            "NFS export flags (rw,sync,no_subtree_check) and reload exports."
        ),
    ),
    "simulate_minio_service_error": FixStrategy(
        fix_type="service_restart",
        fix_commands=[
            (
                "printf '[Unit]\\nDescription=MinIO (fixed)\\n"
                "[Service]\\nExecStart=/bin/true\\nType=oneshot\\n"
                "RemainAfterExit=yes\\n[Install]\\n"
                "WantedBy=multi-user.target\\n' "
                "| sudo tee /etc/systemd/system/minio-broken.service > /dev/null"
            ),
            "sudo systemctl daemon-reload",
            "sudo systemctl enable --now minio-broken",
        ],
        dry_run_commands=["systemctl list-unit-files | grep minio || true"],
        requires_approval=False,
        estimated_risk="low",
        description=(
            "Create the missing minio-broken.service systemd unit file, "
            "reload the daemon, and enable the service."
        ),
    ),
    "simulate_postcheck_error": FixStrategy(
        fix_type="service_restart",
        fix_commands=[
            (
                "nohup python3 -c \""
                "import http.server,socketserver; "
                "h=http.server.SimpleHTTPRequestHandler; "
                "s=socketserver.TCPServer(('',9005),h); "
                "s.serve_forever()\" &>/dev/null &"
            ),
            "sleep 2",
        ],
        dry_run_commands=["ss -tuln | grep 9005 || echo 'Port 9005 not in use'"],
        requires_approval=False,
        estimated_risk="low",
        description=(
            "Start a lightweight HTTP responder on port 9005 so the "
            "MinIO health-check endpoint responds during post-deployment validation."
        ),
    ),
}


class FixGeneratorAgent:
    """
    Generates a concrete FixStrategy from a RootCauseReport.
    Tries the deterministic registry first, then falls back to LLM.
    """

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    # ── Public entry point ────────────────────────────────────

    def generate(self, rca: RootCauseReport) -> FixStrategy:
        task_id = rca.error_report.task_id
        print(f"[FixGenerator] 🔧 Generating fix strategy for: {task_id}")

        # 1. Try the deterministic registry
        strategy = self._lookup_registry(task_id)
        if strategy:
            print(f"[FixGenerator] ✅ Registry match — {strategy.fix_type} "
                  f"({strategy.estimated_risk} risk)")
            return strategy

        # 2. Fall back to LLM-generated fix
        strategy = self._generate_with_llm(rca)
        print(f"[FixGenerator] ✅ LLM-generated fix — {strategy.fix_type} "
              f"({strategy.estimated_risk} risk)")
        return strategy

    # ── Registry lookup ───────────────────────────────────────

    def _lookup_registry(self, task_id: str) -> FixStrategy | None:
        """Exact or substring match against the fix registry."""
        # Strip Airflow mapped-task suffix: simulate_x_error/map_index=0 → simulate_x_error
        clean_id = re.sub(r"/map_index=\d+$", "", task_id)

        # Exact match
        if clean_id in FIX_REGISTRY:
            return FIX_REGISTRY[clean_id].model_copy()
        if task_id in FIX_REGISTRY:
            return FIX_REGISTRY[task_id].model_copy()

        # Substring match (e.g. "simulate_nfs" matches "simulate_nfs_configuration_error")
        for key, strategy in FIX_REGISTRY.items():
            if key in clean_id or clean_id in key:
                return strategy.model_copy()

        return None

    # ── LLM fix generation ────────────────────────────────────

    def _generate_with_llm(self, rca: RootCauseReport) -> FixStrategy:
        """
        Ask the LLM to produce concrete SSH fix commands based
        on the root cause analysis and RAG solution.
        """
        er = rca.error_report

        # Extract the original command that failed from the log
        original_command = self._extract_command_from_log(er.raw_log)

        prompt = f"""You are a senior HPE PCAI infrastructure engineer.
A deployment task failed and needs an automated SSH-based fix.

Task: {er.task_id}
Error Type: {er.error_type}
Error Message: {er.error_message}
Root Cause: {rca.root_cause}
Classification: {rca.classification}
Severity: {rca.severity}
Engineer Action: {rca.engineer_action}
RAG Solution: {er.rag_solution or 'none available'}
Original Command: {original_command or 'not available'}

Generate a fix strategy as ONLY valid JSON:
{{
    "fix_type": "one of: config_correction / service_restart / command_fix / retry",
    "fix_commands": ["list of exact bash commands to run via SSH on the worker node"],
    "dry_run_commands": ["optional verification commands to run first"],
    "estimated_risk": "low / medium / high",
    "description": "one sentence describing what the fix does",
    "requires_approval": true or false
}}

Rules:
- Commands must be idempotent (safe to run multiple times)
- Use sudo where needed
- Be specific — no placeholders
- If unsure, set requires_approval to true and estimated_risk to high"""

        if not self.client:
            return self._build_fallback_strategy(rca)

        try:
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            raw = self._strip_json_fence(raw)
            parsed = json.loads(raw)

            return FixStrategy(
                fix_type=parsed.get("fix_type", "command_fix"),
                fix_commands=parsed.get("fix_commands", [rca.engineer_action]),
                dry_run_commands=parsed.get("dry_run_commands", []),
                estimated_risk=parsed.get("estimated_risk", "medium"),
                description=parsed.get("description", rca.engineer_action),
                requires_approval=parsed.get("requires_approval", True),
            )
        except Exception as exc:
            print(f"[FixGenerator] LLM fix generation failed: {exc}")
            return self._build_fallback_strategy(rca)

    # ── Helpers ───────────────────────────────────────────────

    def _build_fallback_strategy(self, rca: RootCauseReport) -> FixStrategy:
        """Minimal fallback when LLM is unavailable."""
        return FixStrategy(
            fix_type="retry",
            fix_commands=[],
            dry_run_commands=[],
            estimated_risk="high",
            description=f"Fallback: {rca.engineer_action}",
            requires_approval=True,
        )

    def _extract_command_from_log(self, raw_log: str) -> str | None:
        """Try to extract the SSH command that was executed from the Airflow log."""
        match = re.search(r"Running command:\s*\n(.+?)(?:\n\[|$)", raw_log, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _strip_json_fence(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()
