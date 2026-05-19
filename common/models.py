# common/models.py
from pydantic import BaseModel, Field
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
    rag_error_location: Optional[str] = None
    rag_diagnosis: Optional[str] = None
    rag_solution: Optional[str] = None
    rag_prevention: Optional[str] = None
    rag_sources: list[str] = Field(default_factory=list)

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


# ── Phase 2: Autofix models ──────────────────────────────────

class FixStrategy(BaseModel):
    fix_type: str                                   # config_correction / service_restart / command_fix / retry
    fix_commands: list[str]                          # SSH commands to execute on the worker node
    target_node_ip: Optional[str] = None             # which node to fix (None = all nodes)
    requires_approval: bool = True                   # whether human must approve before execution
    dry_run_commands: list[str] = Field(default_factory=list)  # safe verification commands to run first
    estimated_risk: str = "medium"                   # low / medium / high
    description: str                                 # human-readable fix description

class FixResult(BaseModel):
    fix_strategy: FixStrategy
    execution_status: str                            # pending_approval / approved / executing / success / failed / skipped
    command_outputs: list[dict] = Field(default_factory=list)  # stdout/stderr from each command
    error_on_fix: Optional[str] = None               # if the fix itself failed
    retry_dag_run_id: Optional[str] = None           # new DAG run ID after fix
    retry_outcome: Optional[str] = None              # success / still_failing / pending
    attempt_number: int = 1
    max_attempts: int = 2

# ── Phase 3: Validation models ────────────────────────────────
class ValidationReport(BaseModel):
    is_valid: bool                                   # True if fix succeeded and environment is clean
    health_check_output: str                         # Output of SSH verification commands
    queue_status: str                                # Information about lingering errors in the queue
    collateral_damage_check: str                     # Did we break anything else?
    verdict: str                                     # Final human-readable verdict
    escalated_errors: list[dict] = Field(default_factory=list) # Any new/lingering errors found

# ── Phase 2 Hybrid: DAG Analysis + Patching models ───────────

class RagMatch(BaseModel):
    command: str
    description: str
    flags: str
    usage: str

class RagContext(BaseModel):
    commands_found: list[str]
    matches: list[RagMatch]

class DagAnalysisReport(BaseModel):
    has_dag_issues: bool                                       # True if DAG source code has problems
    issues: list[dict] = Field(default_factory=list)           # [{task_id, broken_command, explanation, suggested_fix}]
    corrected_source: Optional[str] = None                     # Full corrected Python source code
    rag_context_used: Optional[RagContext] = None              # RAG entries that were consulted

class DagPatchResult(BaseModel):
    dag_written: bool                                          # Whether remediation_workflow.py was written
    remediation_dag_id: str = "remediation_workflow"           # DAG ID of the corrected DAG
    dag_run_id: Optional[str] = None                           # Airflow run ID for the triggered run
    run_outcome: str = "pending"                               # pending / success / failed / timeout
    attempt_number: int = 1                                    # Which attempt this is (1 or 2)
    failed_tasks: list[str] = Field(default_factory=list)      # Tasks that still failed in remediation DAG

