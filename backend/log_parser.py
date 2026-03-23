import re
from dataclasses import dataclass
from typing import List, Literal, Optional


TaskState = Literal["failed", "success", "running", "unknown"]


@dataclass
class ParsedTaskSection:
    task_id: str
    state: TaskState
    evidence: List[str]
    raw_text: str


@dataclass
class AgentFailurePayload:
    failed_task: str
    task_state: TaskState
    log_text: str
    timestamp: Optional[str]


def extract_task_sections(logs: str) -> List[ParsedTaskSection]:
    sections: List[ParsedTaskSection] = []
    pattern = re.compile(r"^===== task_id=(.+?) =====\s*$", re.MULTILINE)
    matches = list(pattern.finditer(logs))

    for index, match in enumerate(matches):
        task_id = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(logs)
        body = logs[start:end].strip()

        state: TaskState = "unknown"
        if re.search(r"Marking task as FAILED|Task failed with exception|ERROR - Failed to execute job", body):
            state = "failed"
        elif re.search(r"Marking task as SUCCESS", body):
            state = "success"
        elif re.search(r"\[running\]", body, re.IGNORECASE):
            state = "running"

        evidence = _extract_evidence_lines(body)
        sections.append(
            ParsedTaskSection(
                task_id=task_id,
                state=state,
                evidence=evidence,
                raw_text=body,
            )
        )

    return sections


def build_llm_log_context(logs: str) -> tuple[str, List[str], List[str]]:
    sections = extract_task_sections(logs)
    if not sections:
        truncated = logs[-6000:] if len(logs) > 6000 else logs
        return truncated, [], []

    failed_tasks: List[str] = []
    successful_tasks: List[str] = []
    blocks: List[str] = []

    for section in sections:
        if section.state == "failed":
            failed_tasks.append(section.task_id)
        elif section.state == "success":
            successful_tasks.append(section.task_id)

        evidence = "\n".join(f"- {line}" for line in section.evidence)
        blocks.append(f"TASK: {section.task_id}\nSTATE: {section.state}\nEVIDENCE:\n{evidence}")

    return "\n\n".join(blocks), failed_tasks, successful_tasks


def build_agent_failure_payloads(logs: str) -> List[AgentFailurePayload]:
    sections = extract_task_sections(logs)
    payloads: List[AgentFailurePayload] = []

    for section in sections:
        if section.state == "failed":
            payloads.append(
                AgentFailurePayload(
                    failed_task=section.task_id,
                    task_state=section.state,
                    log_text=section.raw_text,
                    timestamp=_extract_timestamp(section.raw_text),
                )
            )

    if payloads:
        return payloads

    fallback_task = _extract_fallback_task_id(logs)
    fallback_state: TaskState = (
        "failed"
        if re.search(r"Marking task as FAILED|Task failed with exception|ERROR - Failed to execute job", logs)
        else "unknown"
    )
    if fallback_task and fallback_state == "failed":
        return [
            AgentFailurePayload(
                failed_task=fallback_task,
                task_state=fallback_state,
                log_text=logs,
                timestamp=_extract_timestamp(logs),
            )
        ]

    return []


def build_agent_failure_payload(logs: str) -> Optional[AgentFailurePayload]:
    payloads = build_agent_failure_payloads(logs)
    return payloads[0] if payloads else None


def _extract_evidence_lines(body: str) -> List[str]:
    specific_error_patterns = [
        r"os baseline validation failed",
        r"unknown keyword",
        r"does not exist",
        r"connection refused",
        r"failed to connect",
        r"unable to locate package",
        r"temporary failure in name resolution",
        r"sudo:.*password",
        r"permission denied",
        r"unit file .* does not exist",
        r"curl\s*:?\s*\(\d+\)",
        r"exportfs:",
        r"mount\.nfs:",
        r"command not found",
        r"failed to enable unit",
        r"job for .* failed",
    ]
    generic_noise_patterns = [
        r"Task failed with exception",
        r"ERROR - Failed to execute job",
        r"SSH operator error: exit status",
        r"Marking task as FAILED",
        r"Traceback \(most recent call last\):",
        r"airflow\.exceptions\.AirflowException",
    ]

    evidence_lines: List[str] = []
    fallback_lines: List[str] = []

    for line in body.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean:
            continue

        if any(re.search(pattern, clean, re.IGNORECASE) for pattern in specific_error_patterns):
            evidence_lines.append(clean)
            continue

        if any(re.search(pattern, clean, re.IGNORECASE) for pattern in generic_noise_patterns):
            continue

        if re.search(
            r"ERROR|failed|exception|refused|timed out|unable to|sudo:|curl:|exportfs:|does not exist",
            clean,
            re.IGNORECASE,
        ):
            fallback_lines.append(clean)

    deduped: List[str] = []
    for line in evidence_lines + fallback_lines:
        if line not in deduped:
            deduped.append(line)
        if len(deduped) >= 4:
            break

    if deduped:
        return deduped

    fallback: List[str] = []
    for line in body.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and not any(re.search(pattern, clean, re.IGNORECASE) for pattern in generic_noise_patterns):
            fallback.append(clean)
        if len(fallback) >= 3:
            break

    return fallback


def _extract_timestamp(body: str) -> Optional[str]:
    match = re.search(r"\[(\d{4}-\d{2}-\d{2}T[^\]]+)\]", body)
    return match.group(1) if match else None


def _extract_fallback_task_id(body: str) -> Optional[str]:
    patterns = [
        r"task_id=([^\s,]+)",
        r"TaskInstance:\s+[^\.\s]+\.([^\s]+)",
        r"Subtask\s+([^\s]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None
