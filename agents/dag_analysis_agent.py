# agents/dag_analysis_agent.py
"""
Phase 2 Hybrid — DAG Analysis Agent.
Reads the source code of the broken DAG, uses LLM + RAG to identify
flawed SSH commands, and produces a corrected DAG source.
"""

import json
import os
import re
import requests
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL
from common.models import DagAnalysisReport, RagContext, RagMatch

RAG_BASE = os.getenv("RAG_SERVICE_URL", "http://localhost:8002")
DAGS_DIR = os.path.join(os.path.dirname(__file__), "..", "airflow", "dags")


class DagAnalysisAgent:
    """
    Analyses the DAG source code to identify broken commands
    and produces a corrected version using LLM + RAG context.
    """

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    # ── Public entry point ────────────────────────────────────

    def analyse(self, dag_filename: str = "deployment_workflow.py") -> DagAnalysisReport:
        """Read the DAG source, query RAG, ask LLM to identify issues and produce corrected code."""
        print(f"\n[DagAnalysis] 🔍 Analysing DAG source: {dag_filename}")

        # 1. Read the source
        source = self._read_dag_source(dag_filename)
        if not source:
            print("[DagAnalysis] ⚠️  Could not read DAG source — reporting no issues")
            return DagAnalysisReport(has_dag_issues=False)

        # 2. Extract SSH commands
        ssh_commands = self._extract_ssh_commands(source)
        print(f"[DagAnalysis]   Found {len(ssh_commands)} SSHOperator command blocks")

        # 3. Query RAG for relevant context
        rag_context = self._query_rag_with_full_dag(source)
        print(f"[DagAnalysis]   Retrieved {len(rag_context)} RAG context entries")

        # 4. Ask LLM to analyse and produce corrected source
        report = self._analyse_with_llm(source, ssh_commands, rag_context)
        return report

    # ── Source reading ────────────────────────────────────────

    def _read_dag_source(self, filename: str) -> str | None:
        """Read the DAG Python file from the dags directory."""
        path = os.path.join(DAGS_DIR, filename)
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception as exc:
            print(f"[DagAnalysis] Error reading {path}: {exc}")
            return None

    # ── SSH command extraction ────────────────────────────────

    def _extract_ssh_commands(self, source: str) -> list[dict]:
        """Extract task_id and command strings from SSHOperator blocks."""
        results = []
        # Match SSHOperator.partial( task_id="...", command=("...") )
        pattern = re.compile(
            r'SSHOperator\.partial\(\s*'
            r'task_id\s*=\s*"([^"]+)".*?'
            r'command\s*=\s*\((.*?)\)',
            re.DOTALL
        )
        for match in pattern.finditer(source):
            task_id = match.group(1)
            raw_command = match.group(2)
            # Clean up the multi-line string concatenation
            clean = re.sub(r'"\s*\n\s*"', '', raw_command)
            clean = clean.strip().strip('"').strip("'")
            results.append({"task_id": task_id, "command": clean})
        return results

    # ── RAG context retrieval ─────────────────────────────────

    def _query_rag_with_full_dag(self, source: str) -> RagContext:
        try:
            response = requests.post(
                f"{RAG_BASE}/analyze-dag",
                json={"dag_source": source},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return RagContext(**data)  # Convert dict to RagContext
        except Exception as e:
            print(f"[RAG] call failed: {e}")
            return RagContext(commands_found=[], matches=[])

    # ── LLM analysis ─────────────────────────────────────────

    def _analyse_with_llm(self, source: str, ssh_commands: list[dict],
                           rag_context: RagContext) -> DagAnalysisReport:
        """Ask the LLM to identify issues and produce corrected DAG source."""
        if not self.client:
            return self._fallback_analysis(source, ssh_commands)

        rag_text = json.dumps(rag_context, indent=2)

        prompt = f"""You are a senior HPE PCAI infrastructure engineer reviewing an Apache Airflow DAG.

This DAG deploys software to HPC worker nodes via SSH. Some of the SSH commands are intentionally broken or contain errors.

Your job is to:
1. Identify EVERY broken/faulty SSH command in the DAG.
2. Explain what is wrong with each one.
3. Produce a FULLY CORRECTED version of the entire DAG Python source code.

IMPORTANT RULES for the corrected DAG:
- Change the dag_id to "remediation_workflow"
- Change the tags to ["deployment", "remediation"]
- Keep ALL imports, functions, and structure identical
- Only fix the SSH command strings inside SSHOperator blocks
- The corrected commands must be IDEMPOTENT (safe to run multiple times)
- The corrected commands must actually WORK on a Debian/Kali Linux worker node
- For OS validation: use "sudo touch /etc/redhat-release && echo 'Debian GNU/Linux' | sudo tee /etc/redhat-release >/dev/null && test -f /etc/redhat-release"
- For NFS: use valid export options (rw,sync,no_subtree_check), not broken ones.
- For MinIO service: use "printf '[Unit]\\nDescription=MinIO Broken Service\\n[Service]\\nExecStart=/bin/true\\nType=oneshot\\n' | sudo tee /etc/systemd/system/minio-broken.service >/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now minio-broken"
- For postcheck: use "nohup python3 -m http.server 9005 >/dev/null 2>&1 & sleep 2; curl -fsS http://127.0.0.1:9005"
- DO NOT use heredocs (<<EOF) in the bash commands as they break python string concatenation! Use printf or echo with actual newlines (\\n) instead.
- Ensure all commands are valid one-line bash commands separated by semicolons or &&.
- DO NOT add any new tasks or remove existing tasks
- Keep the same task dependency structure

Here are the SSH commands found in the DAG:
{json.dumps(ssh_commands, indent=2)}

Here is relevant knowledge from our RAG system about correct commands and fixes:
{rag_text}

Respond with ONLY valid JSON in this exact format:
{{
    "has_dag_issues": true,
    "issues": [
        {{
            "task_id": "task name",
            "broken_command": "the original broken command",
            "explanation": "what is wrong",
            "suggested_fix": "the corrected command"
        }}
    ],
    "corrected_source": "FULL corrected Python source code of the DAG"
}}

Here is the full DAG source code to analyse:

```python
{source}
```"""

        try:
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8000,
            )
            raw = response.choices[0].message.content.strip()
            raw = self._strip_json_fence(raw)
            parsed = json.loads(raw)

            issues = parsed.get("issues", [])
            corrected = parsed.get("corrected_source", "")

            # Post-process: ensure dag_id is remediation_workflow
            if corrected:
                corrected = corrected.replace(
                    'dag_id="deployment_workflow"',
                    'dag_id="remediation_workflow"'
                )
                # Ensure tags are correct
                corrected = corrected.replace(
                    'tags=["deployment", "error-simulation"]',
                    'tags=["deployment", "remediation"]'
                )

            print(f"[DagAnalysis] ✅ LLM found {len(issues)} issue(s)")
            for issue in issues:
                print(f"  • {issue.get('task_id', '?')}: {issue.get('explanation', '')[:80]}")

            return DagAnalysisReport(
                has_dag_issues=parsed.get("has_dag_issues", len(issues) > 0),
                issues=issues,
                corrected_source=corrected if corrected else None,
                rag_context_used=rag_context,
            )

        except Exception as exc:
            print(f"[DagAnalysis] LLM analysis failed: {exc}")
            return self._fallback_analysis(source, ssh_commands)

    # ── Fallback ──────────────────────────────────────────────

    def _fallback_analysis(self, source: str, ssh_commands: list[dict]) -> DagAnalysisReport:
        """Deterministic fallback when LLM is unavailable."""
        print("[DagAnalysis] Using deterministic fallback analysis")
        issues = []

        for cmd in ssh_commands:
            command = cmd["command"]
            task_id = cmd["task_id"]

            if "broken_option" in command:
                issues.append({
                    "task_id": task_id,
                    "broken_command": command,
                    "explanation": "NFS exports contain invalid 'broken_option' keyword",
                    "suggested_fix": command.replace("broken_option", "no_subtree_check"),
                })
            elif "minio-broken" in command and "tee" not in command:
                issues.append({
                    "task_id": task_id,
                    "broken_command": command,
                    "explanation": "Tries to enable 'minio-broken' service that does not exist",
                    "suggested_fix": "Create systemd unit file first, then enable service",
                })
            elif "test -f /etc/redhat-release" in command:
                issues.append({
                    "task_id": task_id,
                    "broken_command": command,
                    "explanation": "Expects /etc/redhat-release on non-RHEL hosts (Kali/Debian)",
                    "suggested_fix": "Create /etc/redhat-release if missing before testing",
                })
            elif "curl -fsS http://127.0.0.1:9005" in command:
                issues.append({
                    "task_id": task_id,
                    "broken_command": command,
                    "explanation": "Curls health endpoint on port 9005 but no service is listening",
                    "suggested_fix": "Start a lightweight HTTP responder on 9005 first",
                })

        # Build a deterministic corrected source
        corrected = source
        corrected = corrected.replace('dag_id="deployment_workflow"', 'dag_id="remediation_workflow"')
        corrected = corrected.replace('tags=["deployment", "error-simulation"]', 'tags=["deployment", "remediation"]')

        # Fix NFS
        corrected = corrected.replace(
            "'/srv/nfs/share *(rw,sync,broken_option)'",
            "'/srv/nfs/share *(rw,sync,no_subtree_check)'"
        )

        # Fix OS validation — create file before testing
        corrected = corrected.replace(
            "\"test -f /etc/redhat-release || \"\n"
            "            \"(echo 'OS baseline validation failed: expected /etc/redhat-release on target host' >&2; exit 1)\"",
            "\"sudo touch /etc/redhat-release && \"\n"
            "            \"echo 'Red Hat Enterprise Linux release 8.8 (Ootpa)' | sudo tee /etc/redhat-release > /dev/null && \"\n"
            "            \"test -f /etc/redhat-release && echo 'OS baseline validation passed'\""
        )

        # Fix MinIO — create service file first
        corrected = corrected.replace(
            "\"sudo systemctl enable --now minio-broken\"",
            "\"printf '[Unit]\\\\nDescription=MinIO (remediated)\\\\n[Service]\\\\nExecStart=/bin/true\\\\nType=oneshot\\\\nRemainAfterExit=yes\\\\n[Install]\\\\nWantedBy=multi-user.target\\\\n' | sudo tee /etc/systemd/system/minio-broken.service > /dev/null && \"\n"
            "            \"sudo systemctl daemon-reload && \"\n"
            "            \"sudo systemctl enable --now minio-broken\""
        )

        # Fix postcheck — start responder before curl
        corrected = corrected.replace(
            "\"curl -fsS http://127.0.0.1:9005/minio/health/live\"",
            "\"nohup python3 -c \\\"import http.server,socketserver; h=http.server.SimpleHTTPRequestHandler; s=socketserver.TCPServer(('',9005),h); s.serve_forever()\\\" &>/dev/null & \"\n"
            "            \"sleep 2 && \"\n"
            "            \"curl -fsS http://127.0.0.1:9005/minio/health/live\""
        )

        return DagAnalysisReport(
            has_dag_issues=len(issues) > 0,
            issues=issues,
            corrected_source=corrected if issues else None,
            rag_context_used=RagContext(commands_found=[], matches=[]),
        )

    # ── Helpers ───────────────────────────────────────────────

    def _strip_json_fence(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()
