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
from common.config import GROQ_API_KEY, GROQ_MODEL, RAG_API_URL
from common.models import DagAnalysisReport

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
        rag_json = self._query_rag_with_full_dag(source)
        print(f"[DagAnalysis]   Retrieved {len(rag_json.get('matches', []))} RAG context entries")
        # rag_json is a dict with keys: 'commands_found' and 'matches'

        # 3.5 Format RAG json
        format_ragjson = self._format_rag_response(rag_json)
        print(f"[DagAnalysis]   Formatted RAG context:\n{format_ragjson}")


        # 4. Ask LLM to analyse and produce corrected source
        report = self._analyse_with_llm(source, ssh_commands, format_ragjson)
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

    def _query_rag_with_full_dag(self, source: str) -> dict:
        #Query RAG API and return raw JSON response.
        try:
            response = requests.post(
                f"{RAG_API_URL}/analyze-dag",
                json={"dag_source": source},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()  # Return raw JSON dict
        except Exception as e:
            print(f"[RAG] call failed: {e}")
            return {"commands_found": [], "matches": []}  # Return empty JSON structure on error
        
    def _format_rag_response(self, rag_json: dict) -> str:
        """Format the RAG JSON response into a readable string."""
        if not rag_json.get("commands_found") and not rag_json.get("matches"):
            return "No commands found or matches available."
        
        output_lines = []
        
        # Format commands found
        commands = rag_json.get("commands_found", [])
        if commands:
            output_lines.append(f"Commands Found ({len(commands)}):")
            for cmd in commands:
                output_lines.append(f"  • {cmd}")
            output_lines.append("")
        
        # Format matches with documentation
        matches = rag_json.get("matches", [])
        if matches:
            output_lines.append(f"Documentation Matches ({len(matches)}):")
            for i, match in enumerate(matches, 1):
                output_lines.append(f"\n  {i}. {match.get('command', 'Unknown')}")
                output_lines.append(f"     Description: {match.get('description', 'N/A')}")
                output_lines.append(f"     Usage: {match.get('usage', 'N/A')}")
                if match.get('flags'):
                    output_lines.append(f"     Flags: {match.get('flags', 'N/A')}")
                output_lines.append("-" * 50)
        
        return "\n".join(output_lines)

    # ── LLM analysis ─────────────────────────────────────────

    def _analyse_with_llm(self, source: str, ssh_commands: list[dict],
                           rag_text: str) -> DagAnalysisReport:
        """Ask the LLM to identify issues and produce corrected DAG source."""
        if not self.client:
            raise ValueError("Groq client not initialized. Cannot perform DAG analysis without LLM.")

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
- For postcheck: use "curl -fsS http://127.0.0.1:9005/minio/health/live"
- For validate_nfs_consistency: use "test -f {{NFS_MOUNT_POINT}}/check.txt || printf '%s\\n' 'deployment-check' | sudo tee {{NFS_MOUNT_POINT}}/check.txt >/dev/null; EXPECTED_NFS=$(cat /tmp/pcai_nfs_a_export); CURRENT_NFS=$(findmnt -n -o SOURCE {{NFS_MOUNT_POINT}}); test '$CURRENT_NFS' = '$EXPECTED_NFS' || (echo 'NFS mount inconsistency detected' >&2; exit 1); grep -qx 'deployment-check' {{NFS_MOUNT_POINT}}/check.txt"
- DO NOT use heredocs (<<EOF) in the bash commands as they break python string concatenation! Use printf or echo with actual newlines (\\n) instead.
- STRICT RULE: Do NOT use f-strings (f"...") or inline variables for complex bash commands. You MUST use standard multiline python strings (e.g., using `"""`) and explicit string formatting, or simple string concatenation. Avoid any unescaped backslashes or curly braces inside python strings.
- Ensure all commands are valid one-line bash commands separated by semicolons or &&, or properly formatted multiline strings.
- NEVER place bash semicolons outside the Python string quotes. All bash logic must remain strictly inside the string.
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

                # Neuter the PythonOperator that sabotages NFS in the Verification DAG
                corrected = corrected.replace(
                    'f"sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "',
                    '"echo \'Skipping simulation in remediation workflow\'; "'
                )
                corrected = corrected.replace(
                    'f"sudo rmdir {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "',
                    '"echo \'Skipping simulation in remediation workflow\'; "'
                )

                # Validate the generated code is valid Python syntax
                import ast
                try:
                    ast.parse(corrected)
                except SyntaxError as e:
                    print(f"[DagAnalysis] ⚠️ LLM generated invalid python code: {e}. Escalating.")
                    raise ValueError(f"LLM generated invalid python code: {e}")

            print(f"[DagAnalysis] ✅ LLM found {len(issues)} issue(s)")
            for issue in issues:
                print(f"  • {issue.get('task_id', '?')}: {issue.get('explanation', '')[:80]}")

            return DagAnalysisReport(
                has_dag_issues=parsed.get("has_dag_issues", len(issues) > 0),
                issues=issues,
                corrected_source=corrected if corrected else None,
                rag_context_used=rag_text,
            )

        except Exception as exc:
            print(f"[DagAnalysis] LLM analysis failed: {exc}")
            raise

    # ── Helpers ───────────────────────────────────────────────

    def _strip_json_fence(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()
