import argparse
import json
import os
from pathlib import Path
from typing import Optional

from llm_agents import AgentOutputs, run_llm_agents
from log_tools import parse_airflow_log


def _load_simple_env(env_path: Path) -> None:
    """Loads KEY=VALUE pairs into environment if not already set."""
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def format_basic_report(
    log_name: str,
    parsed,
    llm_outputs: Optional[AgentOutputs],
    llm_model: str,
    llm_error: str | None,
) -> str:
    lines = [
        f"# Incident Report: {log_name}",
        "",
        "## Execution Mode",
        f"- LLM executed: {'yes' if llm_outputs else 'no'}",
        f"- LLM model: {llm_model}",
        f"- LLM error: {llm_error or 'none'}",
        "",
        "## Parsed Context",
        f"- DAG: {parsed.dag_id or 'unknown'}",
        f"- Task: {parsed.task_id or 'unknown'}",
        f"- Error Type: {parsed.error_type}",
        f"- Error Message: {parsed.error_message}",
        f"- Exit Code: {parsed.exit_code if parsed.exit_code is not None else 'unknown'}",
        "",
        "## Evidence",
    ]

    if parsed.evidence_lines:
        for ev in parsed.evidence_lines:
            lines.append(f"- {ev}")
    else:
        lines.append("- No specific evidence lines were matched.")

    if llm_outputs:
        lines.extend([
            "",
            "## Analyzer Agent Output",
            llm_outputs.analyzer_output,
            "",
            "## Root Cause Agent Output",
            llm_outputs.root_cause_output,
            "",
            "## Fix Suggestion Agent Output",
            llm_outputs.fix_suggester_output,
        ])

    return "\n".join(lines)


def analyze_single_log(
    log_path: Path,
    api_key: str,
    model: str,
) -> str:
    text = log_path.read_text(encoding="utf-8")
    parsed = parse_airflow_log(text)
    llm_outputs: Optional[AgentOutputs] = None
    llm_error: str | None = None

    try:
        llm_outputs = run_llm_agents(
            parsed=parsed,
            raw_log_text=text,
            model=model,
            api_key=api_key,
        )
        print(f"LLM agents executed for {log_path.name} using model {model}")
    except Exception as exc:
        llm_error = str(exc)
        print(f"LLM pipeline failed for {log_path.name}: {exc}")

    return format_basic_report(
        log_name=log_path.name,
        parsed=parsed,
        llm_outputs=llm_outputs,
        llm_model=model,
        llm_error=llm_error,
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    # Load root-level and agents-level env files for local runs.
    _load_simple_env(root / ".env")
    _load_simple_env(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="LLM log analyzer")
    parser.add_argument("log_file", help="Path to the log file to analyze")

    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        parser.error("GEMINI_API_KEY was not found. Set it in .env.")

    model = "gemini-2.5-flash"
    target = Path(args.log_file)
    if not target.exists():
        parser.error(f"Log file not found: {target}")

    out_dir = root / "agents/output"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = analyze_single_log(
        target,
        api_key=api_key,
        model=model,
    )
    out_name = f"{target.name}.report.md"
    out_path = out_dir / out_name
    out_path.write_text(report, encoding="utf-8")
    print(f"Analyzed {target} -> {out_path}")

    summary_path = out_dir / "run_summary.json"
    summary_path.write_text(json.dumps({str(target): str(out_path)}, indent=2), encoding="utf-8")
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
