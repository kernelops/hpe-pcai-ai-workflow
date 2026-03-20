import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from models import FailedTaskRecord, ParsedDagRun, TaskRecord


ATTEMPT_PATTERN = re.compile(r"attempt=(\d+)\.log$")
TIMESTAMP_PATTERN = re.compile(r"^\[([^\]]+)\]")
ERROR_PATTERN = re.compile(r"([A-Za-z_][\w.]*(?:Error|Exception))\s*:\s*(.+)$")


def _parse_timestamp(value: str) -> Optional[datetime]:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-5] + text[-5:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _extract_timestamp(line: str) -> Optional[datetime]:
    match = TIMESTAMP_PATTERN.match(line)
    if not match:
        return None
    return _parse_timestamp(match.group(1))


def _extract_json_payload(line: str) -> Optional[Dict[str, Any]]:
    start = line.find("{")
    end = line.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = line[start : end + 1].strip()
    try:
        payload = json.loads(candidate)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_task_id(task_dir_name: str) -> str:
    if task_dir_name.startswith("task_id="):
        return task_dir_name.split("task_id=", 1)[1]
    return task_dir_name


def _extract_major_failure_lines(raw_logs: List[str], max_lines: int = 20) -> List[str]:
    important_patterns = [
        "ERROR -",
        "Marking task as FAILED",
        "Task failed with exception",
        "Traceback (most recent call last):",
        "AirflowException",
        "exit status",
        "failed to start",
        "module is not loaded",
        "No such file or directory",
        "Permission denied",
        "Connection refused",
        "timed out",
    ]

    selected: List[str] = []
    for line in raw_logs:
        normalized = line.strip()
        if not normalized:
            continue
        if any(pattern in normalized for pattern in important_patterns):
            selected.append(normalized)

    if not selected:
        for line in raw_logs[-max_lines:]:
            normalized = line.strip()
            if normalized:
                selected.append(normalized)

    deduped: List[str] = []
    seen = set()
    for line in selected:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
        if len(deduped) >= max_lines:
            break

    return deduped


def _resolve_run_dir(airflow_log_base_path: str, dag_id: str, run_id: str) -> str:
    candidates = [
        os.path.join(airflow_log_base_path, f"dag_id={dag_id}", f"run_id={run_id}"),
        os.path.join(airflow_log_base_path, dag_id, run_id),
        os.path.join(airflow_log_base_path, f"dag_id={dag_id}", run_id),
        os.path.join(airflow_log_base_path, dag_id, f"run_id={run_id}"),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    raise FileNotFoundError(
        f"Could not locate run directory for dag_id='{dag_id}', run_id='{run_id}' under '{airflow_log_base_path}'"
    )


def _latest_attempt_log(task_dir: str) -> Optional[str]:
    if not os.path.isdir(task_dir):
        return None
    attempt_files: List[Tuple[int, str]] = []
    fallback_logs: List[str] = []

    for name in os.listdir(task_dir):
        full = os.path.join(task_dir, name)
        if not os.path.isfile(full):
            continue
        match = ATTEMPT_PATTERN.match(name)
        if match:
            attempt_files.append((int(match.group(1)), full))
        elif name.endswith(".log"):
            fallback_logs.append(full)

    if attempt_files:
        attempt_files.sort(key=lambda item: item[0])
        return attempt_files[-1][1]
    if fallback_logs:
        fallback_logs.sort(key=lambda path: os.path.getmtime(path))
        return fallback_logs[-1]
    return None


def _parse_task_log(log_path: str, task_id: str) -> Dict[str, Any]:
    structured_events: List[Dict[str, Any]] = []
    raw_logs: List[str] = []
    first_timestamp: Optional[datetime] = None
    failure_trace_lines: List[str] = []
    in_traceback = False

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.rstrip("\n")
                raw_logs.append(stripped)

                ts = _extract_timestamp(stripped)
                if ts and first_timestamp is None:
                    first_timestamp = ts

                payload = _extract_json_payload(stripped)
                if payload and "event" in payload:
                    structured_events.append(payload)

                if "Traceback (most recent call last):" in stripped:
                    in_traceback = True
                    failure_trace_lines.append(stripped)
                    continue

                if in_traceback:
                    if TIMESTAMP_PATTERN.match(stripped):
                        in_traceback = False
                    elif not stripped.strip():
                        in_traceback = False
                    else:
                        failure_trace_lines.append(stripped)
    except OSError as exc:
        return {
            "task_id": task_id,
            "status": "unknown",
            "step_number": None,
            "description": "",
            "summary": f"Failed to read log file: {exc}",
            "key_events": [],
            "error_type": "LogReadError",
            "error_message": str(exc),
            "traceback": "",
            "logs": [f"[parser] unable to read: {log_path}"],
            "first_timestamp": None,
        }

    step_number: Optional[int] = None
    description = ""
    progress_messages: List[str] = []
    success_output = ""
    failure_payload: Optional[Dict[str, Any]] = None

    for event in structured_events:
        event_type = event.get("event")
        if event_type == "TASK_START":
            if step_number is None:
                try:
                    step_number = int(event.get("step_number"))
                except (TypeError, ValueError):
                    step_number = None
            description = str(event.get("description") or description or "")
        elif event_type == "TASK_PROGRESS":
            message = str(event.get("message") or "")
            details = event.get("details", "")
            if details == "":
                progress_messages.append(message)
            else:
                progress_messages.append(f"{message} | details={details}")
        elif event_type == "TASK_SUCCESS":
            success_output = str(event.get("output") or "")
        elif event_type == "TASK_FAILURE":
            failure_payload = event

    status = "unknown"
    if any(event.get("event") == "TASK_FAILURE" for event in structured_events):
        status = "failed"
    elif any(event.get("event") == "TASK_SUCCESS" for event in structured_events):
        status = "success"
    else:
        joined = "\n".join(raw_logs)
        if "Marking task as SUCCESS" in joined:
            status = "success"
        elif "Marking task as FAILED" in joined:
            status = "failed"
        elif "UP_FOR_RETRY" in joined:
            status = "failed"

    error_type = ""
    error_message = ""
    traceback_text = ""

    if failure_payload:
        error_type = str(failure_payload.get("error_type") or "")
        error_message = str(failure_payload.get("error_message") or "")
        traceback_text = str(failure_payload.get("traceback") or "")

    if status == "failed" and (not error_type or not error_message):
        for line in reversed(raw_logs):
            match = ERROR_PATTERN.search(line)
            if match:
                error_type = error_type or match.group(1)
                error_message = error_message or match.group(2)
                break

    if status == "failed" and not traceback_text and failure_trace_lines:
        traceback_text = "\n".join(failure_trace_lines)

    if not progress_messages:
        fallback_events = [
            line.split(" - ", 1)[-1].strip()
            for line in raw_logs
            if " INFO - " in line or " WARNING - " in line or " ERROR - " in line
        ]
        progress_messages = fallback_events[:8]

    summary = ""
    if status == "success":
        summary = success_output or (progress_messages[-1] if progress_messages else "Task completed successfully")
    elif status == "failed":
        summary = error_message or (progress_messages[-1] if progress_messages else "Task failed")
    else:
        summary = progress_messages[-1] if progress_messages else "No parsable task status"

    return {
        "task_id": task_id,
        "status": status,
        "step_number": step_number,
        "description": description,
        "summary": summary,
        "key_events": progress_messages[:10],
        "error_type": error_type,
        "error_message": error_message,
        "traceback": traceback_text,
        "logs": raw_logs,
        "first_timestamp": first_timestamp,
    }


def parse_failed_dag_run(airflow_log_base_path: str, dag_id: str, run_id: str) -> Dict[str, Any]:
    run_dir = _resolve_run_dir(airflow_log_base_path, dag_id, run_id)

    task_records: List[Dict[str, Any]] = []
    for entry in os.listdir(run_dir):
        task_dir = os.path.join(run_dir, entry)
        if not os.path.isdir(task_dir):
            continue
        task_id = _normalize_task_id(entry)
        latest_log = _latest_attempt_log(task_dir)
        if latest_log is None:
            continue
        task_records.append(_parse_task_log(latest_log, task_id))

    def _sort_key(item: Dict[str, Any]) -> Tuple[int, datetime, str]:
        raw_step = item.get("step_number")
        step = raw_step if isinstance(raw_step, int) else 10**9
        ts = item.get("first_timestamp") or datetime.max
        return step, ts, item.get("task_id", "")

    task_records.sort(key=_sort_key)

    for idx, record in enumerate(task_records, start=1):
        if record.get("step_number") is None:
            record["step_number"] = idx
        if not record.get("description"):
            record["description"] = f"Task execution for {record['task_id']}"

    parsed = ParsedDagRun(dag_id=dag_id, run_id=run_id)

    failed_index: Optional[int] = None
    for idx, record in enumerate(task_records):
        if record.get("status") == "failed":
            failed_index = idx
            break

    if failed_index is None:
        for record in task_records:
            if record.get("status") == "success":
                parsed.successful_tasks.append(
                    TaskRecord(
                        task_id=record["task_id"],
                        step_number=int(record["step_number"]),
                        description=record["description"],
                        summary=record["summary"],
                        key_events=record["key_events"],
                    )
                )
        return parsed.to_dict()

    for record in task_records[:failed_index]:
        if record.get("status") == "success":
            parsed.successful_tasks.append(
                TaskRecord(
                    task_id=record["task_id"],
                    step_number=int(record["step_number"]),
                    description=record["description"],
                    summary=record["summary"],
                    key_events=record["key_events"],
                )
            )

    failed = task_records[failed_index]
    parsed.failed_task = FailedTaskRecord(
        task_id=failed["task_id"],
        step_number=int(failed["step_number"]),
        description=failed["description"],
        error_type=failed.get("error_type") or "UnknownError",
        error_message=failed.get("error_message") or "No error message extracted",
        traceback=failed.get("traceback") or "",
        logs=_extract_major_failure_lines(failed.get("logs", []), max_lines=20),
    )

    return parsed.to_dict()