from typing import Any, Dict, List


def convert_to_rag_chunks(parsed_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    dag_id = str(parsed_output.get("dag_id", ""))
    run_id = str(parsed_output.get("run_id", ""))
    chunks: List[Dict[str, Any]] = []

    for task in parsed_output.get("successful_tasks", []):
        task_id = str(task.get("task_id", ""))
        step_number = task.get("step_number")
        description = str(task.get("description", ""))
        summary = str(task.get("summary", ""))
        key_events = task.get("key_events", [])

        text = (
            f"DAG: {dag_id}\n"
            f"Run: {run_id}\n"
            f"Task: {task_id}\n"
            f"Step: {step_number}\n"
            f"Status: SUCCESS\n"
            f"Description: {description}\n"
            f"Summary: {summary}\n"
            f"Key Events:\n- " + "\n- ".join(str(event) for event in key_events)
            if key_events
            else (
                f"DAG: {dag_id}\n"
                f"Run: {run_id}\n"
                f"Task: {task_id}\n"
                f"Step: {step_number}\n"
                f"Status: SUCCESS\n"
                f"Description: {description}\n"
                f"Summary: {summary}\n"
            )
        )

        chunks.append(
            {
                "chunk_id": f"{dag_id}:{run_id}:{task_id}",
                "text": text,
                "metadata": {
                    "dag_id": dag_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "step_number": step_number,
                    "is_failed": False,
                },
            }
        )

    failed_task = parsed_output.get("failed_task")
    if isinstance(failed_task, dict):
        task_id = str(failed_task.get("task_id", ""))
        step_number = failed_task.get("step_number")
        description = str(failed_task.get("description", ""))
        error_type = str(failed_task.get("error_type", ""))
        error_message = str(failed_task.get("error_message", ""))
        traceback_text = str(failed_task.get("traceback", ""))
        logs = failed_task.get("logs", [])

        tail_logs = logs[-20:] if isinstance(logs, list) else []
        joined_logs = "\n".join(str(line) for line in tail_logs)

        text = (
            f"DAG: {dag_id}\n"
            f"Run: {run_id}\n"
            f"Task: {task_id}\n"
            f"Step: {step_number}\n"
            f"Status: FAILURE\n"
            f"Description: {description}\n"
            f"Error Type: {error_type}\n"
            f"Error Message: {error_message}\n"
            f"Traceback:\n{traceback_text}\n"
            f"Recent Logs:\n{joined_logs}"
        )

        chunks.append(
            {
                "chunk_id": f"{dag_id}:{run_id}:{task_id}:failed",
                "text": text,
                "metadata": {
                    "dag_id": dag_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "step_number": step_number,
                    "is_failed": True,
                },
            }
        )

    return chunks