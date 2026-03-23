# common/models.py
from pydantic import BaseModel
from typing import Optional

class DeploymentConfig(BaseModel):
    dag_id: str
    node_ips: list[str]
    os_version: str
    spp_version: str
    storage_config: dict = {}

class TaskFailure(BaseModel):
    dag_run_id: str
    task_id: str
    state: str          # failed / upstream_failed
    log_text: str
    timestamp: str

class ErrorReport(BaseModel):
    task_id: str
    error_type: str
    error_message: str
    error_line: Optional[str] = None
    diagnosis: str
    confidence: float
    raw_log: str

class RootCauseReport(BaseModel):
    error_report: ErrorReport
    root_cause: str
    classification: str   # transient / config / hardware / version_mismatch
    severity: str         # critical / high / low
    engineer_action: str

class AlertResult(BaseModel):
    alert_message: str
    severity: str
    channels_notified: list[str]
