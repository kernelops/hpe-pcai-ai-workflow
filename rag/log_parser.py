"""
log_parser.py
Parses raw Airflow log text to extract:
- Error location (task, line number, file)
- Error type
- Error message
- Clean candidate lines for RAG retrieval (INFO/ERROR lines after "Starting attempt")
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ParsedError:
    task_id: Optional[str]
    dag_id: Optional[str]
    error_type: Optional[str]
    error_message: str
    line_number: Optional[int]
    file_path: Optional[str]
    raw_traceback: Optional[str]
    full_log: str
    candidate_lines: List[str] = field(default_factory=list)  # Clean lines for RAG retrieval


# --- Noise patterns: lines that carry no diagnostic value ---
_NOISE_PATTERNS = [
    r"Dependencies all met",
    r"Starting attempt",
    r"Executing <",
    r"Started process \d+",
    r"Running:.*airflow tasks run",
    r"Job \d+: Subtask",
    r"Running <TaskInstance",
    r"Exporting env vars:",
    r"Tmp dir root location",
    r"::group::",
    r"::endgroup::",
    r"Marking task as",
    r"\d+ downstream tasks scheduled",
    r"Task exited with return code",
    r"Failed to execute job \d+",  # generic runner-level message, actual error is in traceback
    r"Post task execution logs",
    r"Pre task execution logs",
    r"DeprecationWarning",
    r"multi-threaded",
    r"Authentication \(password\) successful",
    r"Connected \(version",
    r"Creating ssh_client",
    r"ssh_hook is not provided",
    r"Using connection ID",
    r"No Host Key Verification",
    r"ssh_conn_id to create SSHHook",
]

_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def _extract_log_message(raw_line: str) -> Optional[str]:
    """
    Strips the Airflow log prefix from a line and returns just the message.
    Handles formats like:
      [2026-05-05T08:38:13.346+0000] {ssh.py:526} INFO - actual message here
      [2026-05-05T08:38:23.734+0000] {standard_task_runner.py:110} ERROR - actual message
    Returns None if the line has no recognisable log prefix.
    """
    match = re.search(r"\}\s+(?:INFO|ERROR|WARNING|CRITICAL)\s+-\s+(.+)", raw_line)
    if match:
        return match.group(1).strip()
    return None


def extract_candidate_lines(log_text: str) -> List[str]:
    """
    Extracts clean diagnostic lines from the log for RAG retrieval.

    Strategy:
    1. Find the "Starting attempt N of N" line — everything before it is
       scheduler/queue noise and is discarded.
    2. From the remaining lines keep only INFO and ERROR lines.
    3. Strip the Airflow timestamp+module prefix, leaving just the message.
    4. Drop lines that match known noise patterns.
    5. Drop blank lines and very short lines (< 10 chars) that can't match anything useful.
    """
    lines = log_text.splitlines()

    # Find the start marker
    start_index = 0
    for i, line in enumerate(lines):
        if re.search(r"Starting attempt \d+ of \d+", line, re.IGNORECASE):
            start_index = i
            break

    candidate_lines: List[str] = []

    for raw_line in lines[start_index:]:
        # Only keep INFO and ERROR lines
        if not re.search(r"\}\s+(?:INFO|ERROR)\s+-\s+", raw_line):
            continue

        message = _extract_log_message(raw_line)
        if not message:
            continue

        # Drop noise
        if _NOISE_RE.search(message):
            continue

        # Drop very short lines
        if len(message) < 10:
            continue

        candidate_lines.append(message)

    return candidate_lines


def parse_airflow_log(log_text: str) -> ParsedError:
    """
    Extract structured error info from raw Airflow log text.
    Handles common Airflow log formats.
    """

    # --- Extract DAG and Task ID ---
    dag_id = None
    task_id = None

    dag_match = re.search(r"dag_id=([^\s,\]]+)", log_text)
    if dag_match:
        dag_id = dag_match.group(1)

    task_match = re.search(r"task_id=([^\s,\]]+)", log_text)
    if task_match:
        task_id = task_match.group(1)

    # --- Extract Traceback block ---
    traceback_match = re.search(
        r"(Traceback \(most recent call last\):.*?)(?=\n\n|\Z)",
        log_text,
        re.DOTALL,
    )
    raw_traceback = traceback_match.group(1).strip() if traceback_match else None

    # --- Extract error type and message (last line of traceback) ---
    error_type = None
    error_message = "Unknown error"

    if raw_traceback:
        # Use findall to get ALL matches and take the last one (most specific)
        all_matches = re.findall(r"(\w+(?:Error|Exception|Warning)[^\n]*)", raw_traceback)
        if all_matches:
            full_error = all_matches[-1]
            if ":" in full_error:
                error_type, error_message = full_error.split(":", 1)
                error_type = error_type.strip()
                error_message = error_message.strip()
            else:
                error_type = full_error.strip()
                error_message = full_error.strip()
    else:
        # Fallback: look for ERROR lines in Airflow log format
        error_line_match = re.search(r"ERROR\s+-\s+(.+)", log_text)
        if error_line_match:
            error_message = error_line_match.group(1).strip()

    # --- Extract file path and line number from traceback ---
    file_path = None
    line_number = None

    if raw_traceback:
        file_matches = re.findall(r'File "([^"]+)", line (\d+)', raw_traceback)
        if file_matches:
            file_path, line_str = file_matches[-1]
            line_number = int(line_str)

    # --- Extract candidate lines for RAG ---
    candidate_lines = extract_candidate_lines(log_text)

    if error_message and error_message != "Unknown error":
        if error_message not in candidate_lines:
            candidate_lines.append(error_message)

    return ParsedError(
        task_id=task_id,
        dag_id=dag_id,
        error_type=error_type,
        error_message=error_message,
        line_number=line_number,
        file_path=file_path,
        raw_traceback=raw_traceback,
        full_log=log_text,
        candidate_lines=candidate_lines,
    )


def format_error_location(parsed: ParsedError) -> str:
    """
    Returns a human-readable error location string.
    """
    parts = []
    if parsed.dag_id:
        parts.append(f"DAG: {parsed.dag_id}")
    if parsed.task_id:
        parts.append(f"Task: {parsed.task_id}")
    if parsed.file_path:
        parts.append(f"File: {parsed.file_path}")
    if parsed.line_number:
        parts.append(f"Line: {parsed.line_number}")
    if parsed.error_type:
        parts.append(f"Error Type: {parsed.error_type}")

    return " | ".join(parts) if parts else "Location unknown"
