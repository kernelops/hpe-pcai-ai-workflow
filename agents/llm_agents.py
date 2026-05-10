import json
from dataclasses import dataclass
from typing import Dict

from schemas import ParsedLog


@dataclass
class AgentOutputs:
    analyzer_output: str
    root_cause_output: str
    fix_suggester_output: str


def _build_client(api_key: str):
    try:
        import google.generativeai as genai
    except Exception as exc:
        raise RuntimeError(
            "google-generativeai is not installed. Install with: pip install google-generativeai"
        ) from exc

    genai.configure(api_key=api_key)
    return genai


def _call_gemini(genai_client, model: str, system_prompt: str, user_prompt: str) -> str:
    full_prompt = (
        f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\n"
        f"USER INPUT:\n{user_prompt}"
    )
    response = genai_client.GenerativeModel(model).generate_content(full_prompt)
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        parts = getattr(candidates[0].content, "parts", []) if getattr(candidates[0], "content", None) else []
        joined = "\n".join(getattr(p, "text", "") for p in parts if getattr(p, "text", None)).strip()
        if joined:
            return joined

    raise RuntimeError("Gemini returned an empty response.")


def run_llm_agents(
    parsed: ParsedLog,
    raw_log_text: str,
    model: str,
    api_key: str,
) -> AgentOutputs:
    genai_client = _build_client(api_key=api_key)

    shared_context: Dict[str, object] = {
        "dag_id": parsed.dag_id,
        "task_id": parsed.task_id,
        "error_type": parsed.error_type,
        "error_message": parsed.error_message,
        "exit_code": parsed.exit_code,
        "evidence_lines": parsed.evidence_lines,
    }

    analyzer_system = (
        "You are Analyzer Agent for PCAI Airflow incident logs. "
        "Extract factual observations only. Do not guess. "
        "Return sections exactly: INCIDENT_SUMMARY, DETECTED_SIGNALS, IMPACT_SCOPE."
    )
    analyzer_user = (
        "Analyze this data and log.\n"
        f"Structured context:\n{json.dumps(shared_context, indent=2)}\n\n"
        f"Raw log:\n{raw_log_text}"
    )
    analyzer_output = _call_gemini(genai_client, model, analyzer_system, analyzer_user)

    # Keep only small safety anchors for root cause to reduce prompt size
    # while preventing drift if analyzer output misses key metadata.
    root_guard_context = {
        "task_id": parsed.task_id,
        "error_type": parsed.error_type,
        "exit_code": parsed.exit_code,
    }

    root_cause_system = (
        "You are Root Cause Agent for PCAI infra workflows. "
        "Use analyzer output as primary evidence and guard metadata for consistency. "
        "Return sections exactly: MOST_LIKELY_ROOT_CAUSE, SUPPORTING_EVIDENCE, "
        "ALTERNATIVE_HYPOTHESES, VALIDATION_CHECKS."
    )
    root_cause_user = (
        "Determine the root cause using analyzer output first, then validate against guards.\n\n"
        f"Guard context:\n{json.dumps(root_guard_context, indent=2)}\n\n"
        f"Analyzer output:\n{analyzer_output}\n\n"
        "Do not assume facts not present in analyzer output unless required to resolve contradictions with guard context."
    )
    root_cause_output = _call_gemini(genai_client, model, root_cause_system, root_cause_user)

    fix_agent_system = (
        "You are Fix Suggestion Agent for operations teams. "
        "Provide practical remediation with commands and checks based on root cause output. "
        "Return sections exactly: IMMEDIATE_FIX_STEPS, COMMANDS_TO_RUN, "
        "ROLLBACK_PLAN, PREVENTION_ACTIONS."
    )
    fix_agent_user = (
        "Provide detailed fixes from root cause output; use analyzer output only for additional detail.\n\n"
        f"Root cause output:\n{root_cause_output}\n\n"
        f"Analyzer output:\n{analyzer_output}"
    )
    fix_suggester_output = _call_gemini(genai_client, model, fix_agent_system, fix_agent_user)

    return AgentOutputs(
        analyzer_output=analyzer_output,
        root_cause_output=root_cause_output,
        fix_suggester_output=fix_suggester_output,
    )
