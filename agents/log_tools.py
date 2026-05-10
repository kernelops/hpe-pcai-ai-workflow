import re
from typing import List

from schemas import ParsedLog


def parse_airflow_log(log_text: str) -> ParsedLog:
    dag_match = re.search(r"AIRFLOW_CTX_DAG_ID='([^']+)'", log_text)
    task_match = re.search(r"AIRFLOW_CTX_TASK_ID='([^']+)'", log_text)

    if not dag_match:
        dag_match = re.search(r"dag_id=([^,\s]+)", log_text)
    if not task_match:
        task_match = re.search(r"task_id=([^,\s]+)", log_text)

    dag_id = dag_match.group(1) if dag_match else None
    task_id = task_match.group(1) if task_match else None

    exit_match = re.search(r"exit status\s*=\s*(\d+)", log_text)
    if not exit_match:
        exit_match = re.search(r"return code\s+(\d+)", log_text)
    exit_code = int(exit_match.group(1)) if exit_match else None

    lines = [line.strip() for line in log_text.splitlines() if line.strip()]

    evidence: List[str] = []
    for line in reversed(lines):
        if "ERROR -" in line or "Exception" in line or "failed" in line.lower():
            evidence.append(line)
            break

    error_message = evidence[0] if evidence else "Task failed with non-zero exit status"
    error_type = "Airflow task failure"
    type_match = re.search(r"([A-Za-z_]+(?:Error|Exception))", error_message)
    if type_match:
        error_type = type_match.group(1)

    return ParsedLog(
        dag_id=dag_id,
        task_id=task_id,
        error_type=error_type,
        error_message=error_message,
        exit_code=exit_code,
        evidence_lines=evidence,
    )
