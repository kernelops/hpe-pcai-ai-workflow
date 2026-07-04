# agents/fix_generator_agent.py
"""
Phase 2 — Fix Generator Agent.
Takes a RootCauseReport and produces a concrete FixStrategy
with SSH commands to remediate the failure.

Resolution flow:
1. Query RAG for known fix strategies matching this task + error context.
2. ALWAYS call LLM with: RCA report + known fix context from RAG, if available.
3. LLM decides whether to use/adapt the known fix or generate a novel one.
4. If the LLM is unavailable, return a high-risk manual-review fallback.
"""

import json
import re
import httpx
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL, RAG_API_URL
from common.models import RootCauseReport, FixStrategy


RAG_BASE = RAG_API_URL


class FixGeneratorAgent:
    """
    Generates a concrete FixStrategy from a RootCauseReport.
    Always queries RAG for known fix context, then routes through LLM.
    Does not return hardcoded task fixes before the LLM has reasoned over the actual error.
    """

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    # ── Public entry point ────────────────────────────────────

    def generate(self, rca: RootCauseReport) -> FixStrategy:
        task_id = rca.error_report.task_id
        print(f"[FixGenerator] 🔧 Generating fix strategy for: {task_id}")

        # 1. Query RAG for known fix strategies
        rag_context = self._query_rag_fix_strategies(task_id, rca)
        if rag_context:
            print(f"[FixGenerator] 📚 Got {len(rag_context)} RAG fix strategy match(es)")
        else:
            print("[FixGenerator] ⚠️ No RAG fix strategies found; LLM will use RCA context only")

        # 2. Always call LLM with RAG context
        strategy = self._generate_with_llm(rca, rag_context)
        if strategy:
            print(f"[FixGenerator] ✅ LLM-generated fix — {strategy.fix_type} "
                  f"({strategy.estimated_risk} risk)")
            return strategy

        print("[FixGenerator] ⚠️ LLM unavailable; returning manual-review fallback")
        return self._build_fallback_strategy(rca)

    # ── RAG query ─────────────────────────────────────────────

    def _query_rag_fix_strategies(self, task_id: str, rca: RootCauseReport) -> list[dict]:
        """Query the RAG service for known fix strategies matching this task."""
        clean_id = re.sub(r"/map_index=\d+$", "", task_id)
        clean_id = re.sub(r"/attempt=\d+$", "", clean_id)

        error_context = " ".join(filter(None, [
            rca.error_report.error_type,
            rca.error_report.error_message,
            rca.root_cause,
            rca.engineer_action,
        ]))

        try:
            resp = httpx.post(
                f"{RAG_BASE.rstrip('/')}/query-fix-strategies",
                json={"task_id": clean_id, "error_context": error_context[:500]},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("strategies", [])
            else:
                print(f"[FixGenerator] RAG query returned {resp.status_code}")
                return []
        except Exception as e:
            print(f"[FixGenerator] RAG query failed: {e}")
            return []

    # ── LLM fix generation ────────────────────────────────────

    def _generate_with_llm(self, rca: RootCauseReport, rag_context: list[dict]) -> FixStrategy | None:
        """
        Ask the LLM to produce concrete SSH fix commands based on
        the root cause analysis and known fix strategies from RAG.
        """
        if not self.client:
            return None

        er = rca.error_report
        original_command = self._extract_command_from_log(er.raw_log)

        # Format RAG fix context for the prompt
        rag_section = self._format_rag_context(rag_context)

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

{rag_section}

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
- If a relevant known fix strategy exists in the "Known Fix Strategies from Knowledge Base" section, you MUST use its exact "Fix Commands" and "Verification Commands" list without omitting any commands or altering their logic, as they are tested and correct.
- If the actual error is DIFFERENT from what the known strategies address, generate a novel fix
- If unsure, set requires_approval to true and estimated_risk to high"""

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
            return None

    def _format_rag_context(self, rag_context: list[dict]) -> str:
        """Format RAG fix strategy matches into a readable prompt section."""
        if not rag_context:
            return "Known Fix Strategies from Knowledge Base: None found."

        lines = ["Known Fix Strategies from Knowledge Base:"]
        for i, ctx in enumerate(rag_context, 1):
            try:
                cmds = json.loads(ctx.get("fix_commands", "[]"))
            except (json.JSONDecodeError, TypeError):
                cmds = []
            try:
                dry_cmds = json.loads(ctx.get("dry_run_commands", "[]"))
            except (json.JSONDecodeError, TypeError):
                dry_cmds = []

            lines.append(f"\n--- Strategy {i} (similarity: {ctx.get('similarity', 'N/A')}) ---")
            lines.append(f"Task: {ctx.get('task_id', 'unknown')}")
            lines.append(f"Fix Type: {ctx.get('fix_type', 'unknown')}")
            lines.append(f"Risk: {ctx.get('estimated_risk', 'unknown')}")
            lines.append(f"Description: {ctx.get('description', '')}")
            lines.append(f"Fix Commands: {json.dumps(cmds, indent=2)}")
            if dry_cmds:
                lines.append(f"Verification Commands: {json.dumps(dry_cmds, indent=2)}")

        return "\n".join(lines)

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
