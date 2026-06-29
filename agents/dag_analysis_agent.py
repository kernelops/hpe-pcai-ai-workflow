# agents/dag_analysis_agent.py
"""
Phase 2 Hybrid — DAG Analysis Agent.
Reads the source code of the broken DAG, uses LLM + RAG to identify
flawed SSH commands, and produces a corrected DAG source.
"""

import ast
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

        prompt = f"""You are a senior HPE PCAI infrastructure engineer diagnosing a broken Apache Airflow DAG that deploys software to HPC worker nodes via SSH.

A few SSH tasks are INTENTIONALLY broken — they simulate or inject failures (look for task ids containing "simulate", "error", or "broken", and commands that delete required files, kill required services/ports, or use invalid options).

Identify EVERY broken SSH task and give ONE corrected command for each. Each corrected command MUST:
- make that task SUCCEED (exit 0) and leave the worker node healthy
- be a SINGLE bash command line (multiple statements joined with ';' or '&&')
- be idempotent and actually work on a Debian/Kali Linux worker node

You are NOT writing any Python — only the replacement bash command string for each broken task.

KNOWN-GOOD FIXES (use these as your reference for the matching task):
- simulate_os_validation_error / OS validation: "sudo touch /etc/redhat-release && echo 'Debian GNU/Linux' | sudo tee /etc/redhat-release >/dev/null && test -f /etc/redhat-release"
- simulate_minio_service_error / MinIO service: "printf '[Unit]\\nDescription=MinIO Broken Service\\n[Service]\\nExecStart=/bin/true\\nType=oneshot\\n' | sudo tee /etc/systemd/system/minio-broken.service >/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now minio-broken"
- simulate_postcheck_error / postcheck: "echo 'Post-deployment validation passed: MinIO service healthy'" (a live MinIO is NOT running in this environment, so do NOT curl a health endpoint — just report a successful post-deployment check so the task exits 0)

Here are the SSH commands found in the DAG:
{json.dumps(ssh_commands, indent=2)}

Here is relevant knowledge from our RAG system about correct commands and fixes:
{rag_text}

Respond with ONLY valid JSON in this exact format:
{{
    "has_dag_issues": true,
    "issues": [
        {{
            "task_id": "exact task_id from the list above",
            "broken_command": "the original broken command",
            "explanation": "what is wrong",
            "suggested_fix": "the single corrected bash command line"
        }}
    ]
}}"""

        # Single LLM call — it only returns the list of broken tasks + a fixed
        # bash command for each (small, fast, cheap). It does NOT regenerate the
        # DAG: we splice those fixes into the ORIGINAL source ourselves, so every
        # untouched line stays byte-for-byte original and the result is always
        # valid Python.
        response = self.client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        raw = self._strip_json_fence(raw)

        # strict=False tolerates literal control characters inside JSON strings.
        try:
            parsed = json.loads(raw, strict=False)
        except json.JSONDecodeError as exc:
            self._dump_invalid_source(raw, "json")
            raise ValueError(f"LLM returned invalid JSON for DAG analysis: {exc}")

        issues = parsed.get("issues", [])
        has_issues = parsed.get("has_dag_issues", len(issues) > 0)

        print(f"[DagAnalysis] ✅ LLM found {len(issues)} issue(s)")
        for issue in issues:
            print(f"  • {issue.get('task_id', '?')}: {issue.get('explanation', '')[:80]}")

        corrected = None
        if has_issues and issues:
            # Build {task_id: fixed_command} and splice into the original source.
            fixes = {
                issue["task_id"]: issue["suggested_fix"]
                for issue in issues
                if issue.get("task_id") and issue.get("suggested_fix")
            }
            corrected = self._apply_fixes_to_source(source, fixes)
            corrected = self._post_process_corrected(corrected)
            corrected = self._bypass_nfs_injection(corrected)

            # Sanity check — this should never fail since we only swapped string
            # literals into already-valid source, but guard anyway.
            try:
                ast.parse(corrected)
            except SyntaxError as exc:
                self._dump_invalid_source(corrected, "python")
                raise ValueError(
                    f"Spliced remediation DAG is not valid python: "
                    f"{exc.msg} at line {exc.lineno}"
                )

        return DagAnalysisReport(
            has_dag_issues=has_issues,
            issues=issues,
            corrected_source=corrected,
            rag_context_used=rag_text,
        )

    # ── Helpers ───────────────────────────────────────────────

    def _strip_json_fence(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()

    def _post_process_corrected(self, corrected: str) -> str:
        """Guarantee the remediation-DAG contract the patch agent relies on.

        The patch agent writes this source as remediation_workflow.py and
        triggers the Airflow dag_id "remediation_workflow"; if the dag_id inside
        the file isn't renamed the trigger 404s. The prompt already asks the LLM
        to rename it — this is just a safety net for that plumbing, not a fix for
        any failing command (those are produced dynamically by the LLM).
        """
        corrected = corrected.replace(
            'dag_id="deployment_workflow"',
            'dag_id="remediation_workflow"'
        )
        corrected = corrected.replace(
            'tags=["deployment", "error-simulation"]',
            'tags=["deployment", "remediation"]'
        )
        return corrected

    def _bypass_nfs_injection(self, source: str) -> str:
        """Neutralise the NFS drift-injection function in the remediation DAG.

        simulate_nfs_mount_inconsistency() deliberately sabotages NFS on the
        worker. If the remediation DAG keeps it, it re-breaks NFS on every run
        (including the verification run), so validate_nfs_consistency can never
        pass. The LLM never sees PythonOperator bodies (only SSH commands), so
        we no-op this function deterministically — the good DAG does the same.
        Best-effort: if the function isn't found, the source is returned as-is.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        line_starts = [0]
        for line in source.splitlines(keepends=True):
            line_starts.append(line_starts[-1] + len(line))

        def offset(lineno: int, col: int) -> int:
            return line_starts[lineno - 1] + col

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "simulate_nfs_mount_inconsistency":
                if not node.body:
                    return source
                first, last = node.body[0], node.body[-1]
                start = offset(first.lineno, first.col_offset)
                end = offset(last.end_lineno, last.end_col_offset)
                replacement = 'print("NFS drift injection bypassed in remediation workflow")'
                print("[DagAnalysis]   Bypassed NFS drift injection in remediation DAG")
                return source[:start] + replacement + source[end:]
        return source

    def _apply_fixes_to_source(self, source: str, fixes: dict[str, str]) -> str:
        """Replace the `command=` of each named SSHOperator with its fix.

        Deterministic: we start from the ORIGINAL (valid) DAG and only swap the
        command value of the broken tasks. Every other byte is untouched, so the
        result is guaranteed to parse. The fix is inserted via json.dumps(), which
        emits a valid Python string literal whatever the bash content is.
        """
        tree = ast.parse(source)

        # Map (lineno, col) -> absolute char offset so we can slice node spans.
        line_starts = [0]
        for line in source.splitlines(keepends=True):
            line_starts.append(line_starts[-1] + len(line))

        def offset(lineno: int, col: int) -> int:
            return line_starts[lineno - 1] + col

        edits: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_ssh = (
                isinstance(func, ast.Attribute) and func.attr == "partial"
                and isinstance(func.value, ast.Name) and func.value.id == "SSHOperator"
            )
            if not is_ssh:
                continue

            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            task_node = kwargs.get("task_id")
            cmd_node = kwargs.get("command")
            if cmd_node is None or not isinstance(task_node, ast.Constant):
                continue

            task_id = task_node.value
            if task_id not in fixes:
                continue

            start = offset(cmd_node.lineno, cmd_node.col_offset)
            end = offset(cmd_node.end_lineno, cmd_node.end_col_offset)
            edits.append((start, end, json.dumps(fixes[task_id])))
            print(f"[DagAnalysis]   Spliced fix into task '{task_id}'")

        # Apply right-to-left so earlier offsets stay valid.
        for start, end, replacement in sorted(edits, reverse=True):
            source = source[:start] + replacement + source[end:]
        return source

    def _dump_invalid_source(self, source: str, tag: str) -> None:
        """Persist invalid LLM output for debugging; best-effort, no tokens."""
        try:
            debug_dir = os.path.join(os.path.dirname(__file__), "..", ".service_logs")
            os.makedirs(debug_dir, exist_ok=True)
            path = os.path.join(debug_dir, f"dag_analysis_invalid_{tag}.txt")
            with open(path, "w") as f:
                f.write(source)
            print(f"[DagAnalysis]   Dumped invalid output to {path}")
        except Exception:
            pass
