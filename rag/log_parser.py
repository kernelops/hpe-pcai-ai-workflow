"""
log_parser.py
Parses raw Airflow log text to extract:
- Error location (task, line number, file)
- Error type
- Error message
"""

import re
from dataclasses import dataclass
from typing import Optional


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
        last_line_match = re.search(r"(\w+(?:Error|Exception|Warning)[^\n]*)", raw_traceback)
        if last_line_match:
            full_error = last_line_match.group(1)
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
        else:
            # Fallback 2: look for general exceptions like AirflowException
            exception_match = re.search(r"(\w*Exception):\s*(.+)", log_text)
            if exception_match:
                error_type = exception_match.group(1).strip()
                error_message = exception_match.group(2).strip()

    # --- Extract file path and line number from traceback ---
    file_path = None
    line_number = None

    if raw_traceback:
        # Match: File "/path/to/file.py", line 42, in some_function
        file_matches = re.findall(r'File "([^"]+)", line (\d+)', raw_traceback)
        if file_matches:
            # Take the last (innermost) file reference
            file_path, line_str = file_matches[-1]
            line_number = int(line_str)

    return ParsedError(
        task_id=task_id,
        dag_id=dag_id,
        error_type=error_type,
        error_message=error_message,
        line_number=line_number,
        file_path=file_path,
        raw_traceback=raw_traceback,
        full_log=log_text,
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