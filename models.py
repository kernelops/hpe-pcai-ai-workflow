import json
import logging
import traceback as traceback_module
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class TaskRecord:
    task_id: str
    step_number: int
    description: str
    summary: str
    key_events: List[str] = field(default_factory=list)


@dataclass
class FailedTaskRecord:
    task_id: str
    step_number: int
    description: str
    error_type: str
    error_message: str
    traceback: str
    logs: List[str] = field(default_factory=list)


@dataclass
class ParsedDagRun:
    dag_id: str
    run_id: str
    successful_tasks: List[TaskRecord] = field(default_factory=list)
    failed_task: Optional[FailedTaskRecord] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dag_id": self.dag_id,
            "run_id": self.run_id,
            "successful_tasks": [
                {
                    "task_id": task.task_id,
                    "step_number": task.step_number,
                    "description": task.description,
                    "summary": task.summary,
                    "key_events": task.key_events,
                }
                for task in self.successful_tasks
            ],
            "failed_task": None
            if self.failed_task is None
            else {
                "task_id": self.failed_task.task_id,
                "step_number": self.failed_task.step_number,
                "description": self.failed_task.description,
                "error_type": self.failed_task.error_type,
                "error_message": self.failed_task.error_message,
                "traceback": self.failed_task.traceback,
                "logs": self.failed_task.logs,
            },
        }


class StructuredTaskLogger:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def task_start(self, dag_id: str, task_id: str, step_number: int, description: str) -> None:
        payload = {
            "event": "TASK_START",
            "dag_id": dag_id,
            "task_id": task_id,
            "step_number": step_number,
            "description": description,
        }
        self.logger.info(json.dumps(payload))

    def task_progress(self, message: str, details: Any) -> None:
        payload = {
            "event": "TASK_PROGRESS",
            "message": message,
            "details": details,
        }
        self.logger.info(json.dumps(payload))

    def task_success(self, task_id: str, output: Any) -> None:
        payload = {
            "event": "TASK_SUCCESS",
            "task_id": task_id,
            "output": output,
        }
        self.logger.info(json.dumps(payload))

    def task_failure(self, task_id: str, exc: BaseException) -> None:
        payload = {
            "event": "TASK_FAILURE",
            "task_id": task_id,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
            "traceback": traceback_module.format_exc(),
        }
        self.logger.error(json.dumps(payload))


def run_with_structured_logging(
    *,
    dag_id: str,
    task_id: str,
    step_number: int,
    description: str,
    body: Callable[[StructuredTaskLogger], Any],
    logger: Optional[logging.Logger] = None,
) -> Any:
    task_logger = StructuredTaskLogger(logger=logger)
    task_logger.task_start(
        dag_id=dag_id,
        task_id=task_id,
        step_number=step_number,
        description=description,
    )
    try:
        result = body(task_logger)
        task_logger.task_success(task_id=task_id, output=result)
        return result
    except Exception as exc:
        task_logger.task_failure(task_id=task_id, exc=exc)
        raise