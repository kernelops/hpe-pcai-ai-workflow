"""
fix_generator_agent.py
Phase 2 — Fix Generator Agent.

New RAG-based architecture:
  Prompt RAG (once) — analyzes RAG results + diagnostic outputs → selects fix index
  Prompt RAG_FIX (loop) — analyzes fix execution results → selects next fix index or done
"""

import json
import re
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL
from common.models import RootCauseReport, FixStrategy


ALLOWED_COMMAND_PREFIXES = [
    "which", "ps aux", "sudo systemctl", "ss -tuln", "sudo ufw",
    "sudo iptables", "curl", "wget", "chmod", "sudo mv", "sudo useradd",
    "sudo mkdir", "sudo chown", "sudo tee", "sudo sed", "sudo journalctl",
    "echo", "sleep", "cat", "ls", "sudo usermod", "sudo apt-get",
    "sudo touch", "sudo exportfs", "sudo modprobe", "lsmod",
    "systemctl", "netstat", "ping", "nc", "nohup", "python3",
    "printf", "sudo printf", "id", "uname", "df", "free",
    "mount", "sudo mount", "sudo umount", "sudo rm", "sudo cp",
    "sudo chmod", "sudo chown", "sudo service", "sudo ln",
    "sudo install", "sudo dpkg", "sudo snap", "sudo killall", "sudo kill",
    "test", "stat", "find", "grep", "awk", "sed", "tr", "cut",
    "tar", "gzip", "unzip", "sudo tar", "sudo unzip",
    "docker", "sudo docker", "mc ", "minio ",
    "set -e", "nohup python3",
]


class FixGeneratorAgent:
    """
    Generates fix commands using RAG-based architecture.
    """
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    def get_rag_fix_index(
        self,
        task_id: str,
        raw_log: str,
        rag_entry: dict,
        diagnostic_results: list[dict],
        fix_results = None,
    ) -> dict:
        """
        RAG-based prompt: Analyzes diagnostic results and picks the best fix.
        
        Args:
            task_id: The failed task ID
            raw_log: The raw log from the failure
            rag_entry: The matched RAG entry with fix_possibilities
            diagnostic_results: Results from running diagnostic commands
            fix_results: Results from running fix commands (for subsequent iterations)
        
        Returns:
            {
                "selected_index": 0,  # Index in fix_possibilities, or -1 if none
                "reasoning": "...",
                "phase": "diagnostic" | "fix" | "verification" | "done"
            }
        """

        if not self.client:
            return {
                "selected_index": -1,
                "reasoning": "No LLM client available",
                "phase": "done"
            }

        try:
            # Build prompt based on whether we have fix_results
            if fix_results is None or len(fix_results) ==0:
                prompt = self._build_rag_prompt_diagnostic(task_id, raw_log, rag_entry, diagnostic_results)
            else:
                prompt = self._build_rag_prompt_fix(task_id, raw_log, rag_entry, diagnostic_results, fix_results)
            
            raw = self._call_llm([{"role": "user", "content": prompt}])
            parsed = json.loads(self._strip_json_fence(raw))
            
            print(f"[FixGenerator] Reasoning    : {parsed.get('reasoning')}")
            print(f"[FixGenerator] Selected     : {parsed.get('selected_index')}")
            print(f"[FixGenerator] Phase        : {parsed.get('phase')}")
            
            return parsed
            
        except Exception as exc:
            print(f"[FixGenerator] RAG prompt failed: {exc}")
            return {
                "selected_index": -1,
                "reasoning": f"RAG prompt failed: {exc}",
                "phase": "done"
            }

    def build_fix_strategy(
        self,
        rca: RootCauseReport,
        command_history: list[dict],
        final_reasoning: str,
        estimated_risk: str = "medium",
    ) -> FixStrategy:
        """
        Packages the completed loop history into a FixStrategy.
        """
        dry_run_commands = [
            e["command"] for e in command_history
            if e.get("phase") == "diagnostic"
        ]
        fix_commands = [
            e["command"] for e in command_history
            if e.get("phase") in ("fix", "verification")
        ]

        if not fix_commands and not dry_run_commands:
            fix_commands = [e["command"] for e in command_history]

        return FixStrategy(
            fix_type="rag_iterative",
            fix_commands=fix_commands,
            dry_run_commands=dry_run_commands,
            estimated_risk=estimated_risk,
            description=final_reasoning or (
                f"RAG-based iterative fix for {rca.error_report.task_id} "
                f"— {len(command_history)} commands executed"
            ),
            requires_approval=False,
        )

    # ══════════════════════════════════════════════════════════
    # PROMPT BUILDERS
    # ══════════════════════════════════════════════════════════

    def _build_rag_prompt_diagnostic(
        self,
        task_id: str,
        raw_log: str,
        rag_entry: dict,
        diagnostic_results: list[dict],
    ) -> str:
        """Build prompt for first iteration (diagnostic results only)."""
        
        # Format fix possibilities with indices
        fix_possibilities = rag_entry.get("fix_possibilities", [])
        possibilities_text = ""
        for idx, possibility in enumerate(fix_possibilities):
            possibilities_text += f"  {idx}: {possibility}\n"
        
        # Format diagnostic results
        results_text = "\n\n".join([
            f"$ {r['command']}\n"
            f"EXIT: {r['exit_code']}\n"
            f"OUT: {r['stdout'] or '(empty)'}\n"
            f"ERR: {r['stderr'] or '(empty)'}"
            for r in diagnostic_results
        ])

        return f"""You are an automated infrastructure repair agent for HPE PCAI Linux worker nodes.

A deployment task has failed. You have a RAG (Retrieval-Augmented Generation) entry that matches the error pattern.

TASK ID: {task_id}
RAW LOG: {raw_log}...

RAG ENTRY - FIX POSSIBILITIES:
{possibilities_text}

DIAGNOSTIC COMMANDS EXECUTED AND THEIR OUTPUTS:
{results_text}

Your task:
1. Analyze the diagnostic command outputs above
2. Determine which fix_possibility (by index number) best matches the observed symptoms
3. If none of the possibilities match, return -1

Rules:
- You must select EXACTLY ONE index from the fix_possibilities list (0, 1, 2, 3, etc.)
- If you're unsure, select the most likely one based on the outputs
- Only return -1 if you're confident NONE of the possibilities apply
- This is a bare-metal Debian/Kali Linux node

Respond with ONLY valid JSON:
{{
    "selected_index": 0,
    "reasoning": "one sentence explaining why you selected this index based on the outputs",
    "phase": "diagnostic"
}}

If no fix possibility matches:
{{
    "selected_index": -1,
    "reasoning": "explain why none of the fix possibilities match",
    "phase": "done"
}}"""

    def _build_rag_prompt_fix(
        self,
        task_id: str,
        raw_log: str,
        rag_entry: dict,
        diagnostic_results: list[dict],
        fix_results: list[dict],
    ) -> str:
        """Build prompt for subsequent iterations (diagnostic + fix results)."""
        
        fix_possibilities = rag_entry.get("fix_possibilities", [])
        possibilities_text = ""
        for idx, possibility in enumerate(fix_possibilities):
            possibilities_text += f"  {idx}: {possibility}\n"
        
        # Format diagnostic results (summary)
        diag_text = "\n".join([
            f"$ {r['command']} → EXIT: {r['exit_code']}"
            for r in diagnostic_results[:3]  # Show first few
        ])
        
        # Format fix results
        fix_text = "\n\n".join([
            f"$ {r['command']}\n"
            f"EXIT: {r['exit_code']}\n"
            f"OUT: {r['stdout'] or '(empty)'}\n"
            f"ERR: {r['stderr'] or '(empty)'}"
            for r in fix_results
        ])

        return f"""You are an automated infrastructure repair agent for HPE PCAI Linux worker nodes.

You previously selected a fix from the RAG entry and executed it. Now analyze whether the fix worked.

TASK ID: {task_id}

RAG ENTRY - FIX POSSIBILITIES (previously selected one):
{possibilities_text}

DIAGNOSTIC COMMANDS (summary):
{diag_text}

FIX COMMANDS EXECUTED AND THEIR OUTPUTS:
{fix_text}

Your task:
1. Analyze whether the fix commands succeeded (exit code 0)
2. If the fix was successful and the issue is resolved, return -1 (done)
3. If the fix failed, check if another fix_possibility might work
4. Return the index of the next fix to try, or -1 if done

Rules:
- If exit code is 0 for all fix commands, consider it resolved → return -1
- If the original command returned exit code 0, consider it resolved -> return -1
- If some fix commands failed, consider trying another possibility
- Return the index (0, 1, 2, 3, etc.) of the next fix to try
- Only return -1 if the issue is fully resolved
- This is a bare-metal Debian/Kali Linux node

Respond with ONLY valid JSON:
{{
    "selected_index": 0,
    "reasoning": "one sentence explaining what happened and what to try next",
    "phase": "verification"
}}

If the issue is fully resolved:
{{
    "selected_index": -1,
    "reasoning": "explain why the issue is resolved",
    "phase": "done"
}}"""

    # ══════════════════════════════════════════════════════════
    # HELPERS (unchanged)
    # ══════════════════════════════════════════════════════════

    def _call_llm(self, messages: list[dict]) -> str:
        if self.client is None:
            raise RuntimeError(
                "Groq client not initialized. Please check GROQ_API_KEY is set correctly."
            )

        response = self.client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
        )
        print(response)
        return response.choices[0].message.content.strip()
    
    def _strip_json_fence(self, raw: str) -> str:
        raw = raw.strip()
        
        fence_match = re.search(r"```json\s*(.*?)```", raw, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()
        
        fence_match = re.search(r"```\s*(.*?)```", raw, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1).strip()
            if candidate.startswith("{") or candidate.startswith("["):
                return candidate
        
        start = raw.find('{')
        end = raw.rfind('}')
        
        if start != -1 and end != -1 and start < end:
            return raw[start:end + 1].strip()
        
        return raw.strip()