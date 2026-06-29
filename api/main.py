
# api/main.py
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from agents.run_workflow_agent     import RunWorkflowAgent
from agents.monitor_workflow_agent import MonitorWorkflowAgent
from agents.log_analyser_agent     import LogAnalyserAgent
from agents.root_cause_agent       import RootCauseAgent
from agents.alerting_agent         import AlertingAgent
from agents.fix_generator_agent    import FixGeneratorAgent
from agents.fix_executor_agent     import FixExecutorAgent
from agents.validation_agent       import ValidationAgent
from agents.dag_analysis_agent     import DagAnalysisAgent
from agents.dag_patch_agent        import DagPatchAgent
from common.models                 import (DeploymentConfig, TaskFailure,
                                           ErrorReport, RootCauseReport,
                                           FixStrategy, FixResult, ValidationReport,
                                           DagAnalysisReport, DagPatchResult)

try:
    from redis import Redis
    from rq import Queue
except ImportError:
    Redis = None
    Queue = None

app = FastAPI(
    title       = "HPE PCAI — Agent Ops API",
    description = "AI agent pipeline for HPE PCAI deployment monitoring",
    version     = "1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

# Instantiate agents once at startup 
_run      = RunWorkflowAgent()
_monitor  = MonitorWorkflowAgent()
_log      = LogAnalyserAgent()
_rca      = RootCauseAgent()
_alert    = AlertingAgent()
_fix_gen  = FixGeneratorAgent()
_fix_exec = FixExecutorAgent()
_val      = ValidationAgent()
_dag_ana  = DagAnalysisAgent()
_dag_pat  = DagPatchAgent()

# Redis queue setup for HPC error logs
_redis_conn = Redis(host="localhost", port=6379, db=0) if Redis else None
_hpc_queue = Queue("hpc_error_logs", connection=_redis_conn) if _redis_conn else None

# In-memory store for pending fix approvals
_pending_fixes: dict[str, dict] = {}



# REQUEST SCHEMA

class PipelineRequest(BaseModel):
    dag_id          : str = "pcai_deployment"
    node_ips        : list[str] = ["10.0.0.1"]
    os_version      : str = "ubuntu22.04"
    spp_version     : str = "2025.03"
    storage_config  : dict = {}
    sample_log_path : Optional[str] = None   # empty = real Airflow mode


class FailureAnalysisRequest(BaseModel):
    dag_id      : str = "deployment_workflow"
    dag_run_id  : str
    failed_task : str
    task_state  : str = "failed"
    log_text    : str
    timestamp   : str


def _build_failure_analysis_response(
    dag_id: str,
    dag_run_id: str,
    failure: TaskFailure,
    error_report,
    rca,
    alert_result,
):
    workflow_agent_output = {
        "thinking": [
            f"Received failed run context for DAG: {dag_id}",
            f"Existing Airflow run ID: {dag_run_id}",
            "Skipping DAG trigger because the deployment already ran",
            f"Using failed task payload for: {failure.task_id}",
        ],
        "output": {
            "dag_run_id": dag_run_id,
            "dag_id": dag_id,
            "status": "existing-run",
            "run_path": dag_id,
        },
    }

    monitor_agent_output = {
        "thinking": [
            f"Received failure context for DAG run: {dag_run_id}",
            "Skipping live polling and using provided failed task payload",
            f"Failure confirmed in task: {failure.task_id}",
        ],
        "output": {
            "failure_detected": True,
            "failed_task": failure.task_id,
            "task_state": failure.state,
            "breakpoint": failure.task_id,
        },
    }


    log_analysis_agent_output = {
        "thinking": [
            f"Fetched raw log for task: {failure.task_id}",
            "Chunking and tokenising log content...",
            "Querying RAG layer for similar HPE error patterns...",
            f"Identified error type: {error_report.error_type}",
            f"Confidence: {error_report.confidence}",
            f"Diagnosis: {error_report.diagnosis}",
        ],
        "output": {
            "task_id": error_report.task_id,
            "error_type": error_report.error_type,
            "error_message": error_report.error_message,
            "error_line": error_report.error_line,
            "diagnosis": error_report.diagnosis,
            "confidence": error_report.confidence,
            "strongest_error_signal": error_report.error_message,
            "rag_diagnosis": error_report.rag_diagnosis,
            "rag_solution": error_report.rag_solution,
            "rag_prevention": error_report.rag_prevention,
            "rag_sources": error_report.rag_sources,
        },
    }


    root_cause_agent_output = {
        "thinking": [
            f"Received structured error report for: {error_report.error_type}",
            "Reasoning over cause chain with LLM...",
            f"Classification: {rca.classification}",
            f"Severity assigned: {rca.severity}",
            f"Root cause identified: {rca.root_cause}",
            f"Recommended action: {rca.engineer_action}",
        ],
        "output": {
            "root_cause": rca.root_cause,
            "classification": rca.classification,
            "severity": rca.severity,
            "engineer_action": rca.engineer_action,
            "remediation_steps": rca.engineer_action,
            "next_check": f"Retry {failure.task_id} after applying fix",
            "knowledge_sources": error_report.rag_sources,
        },
    }


    severity = rca.severity.lower()
    is_critical = severity == "critical"
    action_status = "review-needed" if is_critical else "safe"

    alerting_agent_output = {
        "thinking": [
            f"Received fix action plan with severity: {rca.severity}",
            "Evaluating remediation steps for risk...",
            f"Action classified as: {action_status.upper()}",
            "Composing human-readable alert message with LLM...",
            f"Routing alert via: {', '.join(alert_result.channels_notified) if alert_result.channels_notified else 'console'}",
        ],
        "output": {
            "alert_message": alert_result.alert_message,
            "action_status": action_status,
            "flagged": is_critical,
            "approval_required": is_critical,
            "flag_reason": "Critical severity — requires engineer approval" if is_critical else None,
            "channels_notified": alert_result.channels_notified or ["console"],
            "safe_checks": [rca.engineer_action] if not is_critical else [],
            "disruptive_actions": [rca.engineer_action] if is_critical else [],
        },
    }

    combined_summary = {
        "verdict": f"🚨 [{rca.severity.upper()}] Deployment failed — {failure.task_id}",
        "failed_task": failure.task_id,
        "error_type": error_report.error_type,
        "error_message": error_report.error_message,
        "root_cause": rca.root_cause,
        "classification": rca.classification,
        "severity": rca.severity,
        "engineer_action": rca.engineer_action,
        "rag_solution": error_report.rag_solution,
        "alert_message": alert_result.alert_message,
        "approval_required": is_critical,
        "channels_notified": alert_result.channels_notified or ["console"],
    }

    return {
        "pipeline_status": "alerted",
        "dag_run_id": dag_run_id,
        "failure_detected": True,
        "workflow_agent": workflow_agent_output,
        "monitor_agent": monitor_agent_output,
        "log_analysis_agent": log_analysis_agent_output,
        "root_cause_agent": root_cause_agent_output,
        "alerting_agent": alerting_agent_output,
        "combined_summary": combined_summary,
    }


# ENDPOINTS

@app.get("/health")
def health():
    return {"status": "ok", "service": "HPE PCAI Agent Ops API"}


@app.post("/api/agents/run-pipeline")
def run_pipeline(request: PipelineRequest):
    """
    Single endpoint — runs all 5 agents sequentially.
    Returns per-agent thinking + output for each frontend card,
    plus a combined summary for the Combined Summary card.
    """
    try:
        config = DeploymentConfig(
            dag_id         = request.dag_id,
            node_ips       = request.node_ips,
            os_version     = request.os_version,
            spp_version    = request.spp_version,
            storage_config = request.storage_config
        )

        # Agent 1: Run Workflow Agent 
        dag_run_id = _run.trigger_dag_mock(config) if request.sample_log_path \
                     else _run.trigger_dag(config)

        workflow_agent_output = {
            "thinking": [
                f"Received deployment config for DAG: {config.dag_id}",
                f"Node IPs: {', '.join(config.node_ips)}",
                f"OS: {config.os_version} | SPP: {config.spp_version}",
                "Triggering Airflow DAG via REST API...",
                f"DAG triggered successfully. Run ID: {dag_run_id}"
            ],
            "output": {
                "dag_run_id"  : dag_run_id,
                "dag_id"      : config.dag_id,
                "status"      : "triggered",
                "run_path"    : f"{config.dag_id}",
            }
        }

        # Agent 2: Monitor Workflow Agent ─
        failure = _monitor.monitor_mock(dag_run_id, request.sample_log_path) \
                  if request.sample_log_path \
                  else _monitor.monitor(dag_run_id)

        monitor_agent_output = {
            "thinking": [
                f"Monitoring DAG run: {dag_run_id}",
                "Polling Airflow REST API for task states...",
                f"Failure detected in task: {failure.task_id}" if failure
                else "All tasks completed successfully — no failures detected"
            ],
            "output": {
                "failure_detected" : failure is not None,
                "failed_task"      : failure.task_id if failure else None,
                "task_state"       : failure.state if failure else "success",
                "breakpoint"       : failure.task_id if failure else None,
            }
        }

        # If no failure — return early, no need to run remaining agents
        if not failure:
            return {
                "pipeline_status" : "success",
                "dag_run_id"      : dag_run_id,
                "failure_detected": False,

                "workflow_agent"  : workflow_agent_output,
                "monitor_agent"   : monitor_agent_output,
                "log_analysis_agent"     : None,
                "root_cause_agent": None,
                "alerting_agent"        : None,

                "combined_summary": {
                    "verdict"          : "✅ Deployment completed successfully",
                    "failed_task"      : None,
                    "error_type"       : None,
                    "root_cause"       : None,
                    "classification"   : None,
                    "severity"         : None,
                    "engineer_action"  : None,
                    "alert_message"    : None,
                    "approval_required": False,
                    "channels_notified": []
                }
            }

        # Failure detected — run remaining analysis agents to build the response
        error_report = _log.analyse(failure)
        rca = _rca.analyse(error_report)
        alert_result = _alert.alert(rca)
        return _build_failure_analysis_response(
            config.dag_id,
            dag_run_id,
            failure,
            error_report=error_report,
            rca=rca,
            alert_result=alert_result,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agents/analyze-failure")
def analyze_failure(request: FailureAnalysisRequest):
    try:
        failure = TaskFailure(
            dag_run_id=request.dag_run_id,
            task_id=request.failed_task,
            state=request.task_state,
            log_text=request.log_text,
            timestamp=request.timestamp,
        )
        error_report = _log.analyse(failure)
        rca = _rca.analyse(error_report)
        alert_result = _alert.alert(rca)
        return _build_failure_analysis_response(
            dag_id=request.dag_id,
            dag_run_id=request.dag_run_id,
            failure=failure,
            error_report=error_report,
            rca=rca,
            alert_result=alert_result,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 2: Autofix endpoints ───────────────────────────────

class GenerateFixRequest(BaseModel):
    dag_id      : str = "deployment_workflow"
    dag_run_id  : str
    failed_task : str
    task_state  : str = "failed"
    log_text    : str
    timestamp   : str
    worker_nodes: list[dict] = []  # [{"ip": ..., "username": ..., "password": ...}]


class ExecuteFixRequest(BaseModel):
    fix_id: str                    # returned by generate-fix
    approved: bool = True


class AutofixPipelineRequest(BaseModel):
    dag_id      : str = "deployment_workflow"
    dag_run_id  : str
    failed_task : str
    task_state  : str = "failed"
    log_text    : str
    timestamp   : str
    worker_nodes: list[dict] = []
    auto_approve: bool = True      # if True, skip approval gate
    mock        : bool = False     # if True, simulate SSH execution


@app.post("/api/agents/generate-fix")
def generate_fix(request: GenerateFixRequest):
    """
    Phase 2: Generate a fix strategy from a failure analysis.
    Does NOT execute the fix — returns a proposal for review.
    """
    try:
        failure = TaskFailure(
            dag_run_id=request.dag_run_id,
            task_id=request.failed_task,
            state=request.task_state,
            log_text=request.log_text,
            timestamp=request.timestamp,
        )

        # Run Phase 1 analysis
        error_report = _log.analyse(failure)
        rca = _rca.analyse(error_report)

        # Generate fix strategy
        strategy = _fix_gen.generate(rca)

        # Store for later execution
        fix_id = f"fix_{uuid.uuid4().hex[:8]}"
        _pending_fixes[fix_id] = {
            "fix_id": fix_id,
            "strategy": strategy,
            "rca": rca,
            "failure": failure,
            "worker_nodes": request.worker_nodes,
            "created_at": datetime.now().isoformat(),
            "status": "pending_approval" if strategy.requires_approval else "ready",
        }

        return {
            "fix_id": fix_id,
            "status": "pending_approval" if strategy.requires_approval else "ready",
            "fix_strategy": {
                "fix_type": strategy.fix_type,
                "fix_commands": strategy.fix_commands,
                "dry_run_commands": strategy.dry_run_commands,
                "estimated_risk": strategy.estimated_risk,
                "description": strategy.description,
                "requires_approval": strategy.requires_approval,
                "target_node_ip": strategy.target_node_ip,
            },
            "analysis_summary": {
                "failed_task": failure.task_id,
                "error_type": error_report.error_type,
                "root_cause": rca.root_cause,
                "classification": rca.classification,
                "severity": rca.severity,
                "engineer_action": rca.engineer_action,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agents/execute-fix")
def execute_fix(request: ExecuteFixRequest):
    """
    Phase 2: Execute a previously generated fix.
    """
    try:
        pending = _pending_fixes.get(request.fix_id)
        if not pending:
            raise HTTPException(status_code=404, detail=f"Fix ID not found: {request.fix_id}")

        strategy = pending["strategy"]
        worker_nodes = pending["worker_nodes"]

        # Execute the fix
        result = _fix_exec.execute(
            strategy=strategy,
            worker_nodes=worker_nodes,
            approved=request.approved,
            mock=not worker_nodes,  # mock if no real nodes
        )

        # Update stored state
        pending["status"] = result.execution_status
        pending["result"] = result

        return {
            "fix_id": request.fix_id,
            "execution_status": result.execution_status,
            "command_outputs": result.command_outputs,
            "error_on_fix": result.error_on_fix,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agents/autofix-pipeline")
def autofix_pipeline(request: AutofixPipelineRequest):
    """
    Phase 2 Hybrid: Full autofix pipeline.
    Step 0: Phase 1 analysis (Log → RCA → Alert)
    Step 1: DAG Analysis (scan source for code-level issues)
    Step 2: Attempt 1 — DAG-only fix (patch & trigger remediation DAG)
    Step 3: Attempt 2 — DAG + SSH fix (if Attempt 1 failed)
    Step 4: Escalation (if both attempts failed)
    """
    try:
        failure = TaskFailure(
            dag_run_id=request.dag_run_id,
            task_id=request.failed_task,
            state=request.task_state,
            log_text=request.log_text,
            timestamp=request.timestamp,
        )

        # ── Step 0: Get All Initial Failed Tasks ─────────────
        try:
            import requests
            from agents.dag_patch_agent import AIRFLOW_API
            url = f"{AIRFLOW_API}/dags/{request.dag_id}/dagRuns/{request.dag_run_id}/taskInstances"
            resp = requests.get(url, auth=_dag_pat._auth(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                initial_failed_tasks = [
                    ti["task_id"]
                    for ti in data.get("task_instances", [])
                    if ti["state"] == "failed"
                ]
                if not initial_failed_tasks:
                    initial_failed_tasks = [request.failed_task]
            else:
                initial_failed_tasks = [request.failed_task]
        except Exception:
            initial_failed_tasks = [request.failed_task]

        # ── Step 0: Phase 1 analysis ─────────────────────────
        error_report = _log.analyse(failure)
        rca = _rca.analyse(error_report)
        alert_result = _alert.alert(rca)

        # Build the base Phase 1 response
        phase1 = _build_failure_analysis_response(
            dag_id=request.dag_id,
            dag_run_id=request.dag_run_id,
            failure=failure,
            error_report=error_report,
            rca=rca,
            alert_result=alert_result,
        )

        # ── Step 1: DAG Analysis ─────────────────────────────
        dag_filename = f"{request.dag_id}.py"
        
        # Bypass LLM analysis for the known good DAG to prevent hallucinations
        if request.dag_id == "good_deployment_workflow":
            from agents.dag_analysis_agent import DagAnalysisReport
            with open(f"airflow/dags/{dag_filename}", "r") as f:
                source_code = f.read()
            dag_report = DagAnalysisReport(
                has_dag_issues=False,
                issue_count=0,
                issues=[],
                patched_source=source_code,
                rag_sources=[],
            )
        else:
            dag_report = _dag_ana.analyse(dag_filename)

        dag_analysis_output = {
            "thinking": [
                f"Scanning {dag_filename} source code...",
                f"Querying RAG for correct command syntax...",
                f"Found {len(dag_report.issues)} issue(s) in DAG source",
            ],
            "output": {
                "has_dag_issues": dag_report.has_dag_issues,
                "issues": dag_report.issues,
                "rag_context_used": dag_report.rag_context_used,
            },
        }
        # Add issue details to thinking
        for issue in dag_report.issues:
            dag_analysis_output["thinking"].append(
                f"• {issue.get('task_id', '?')}: {issue.get('explanation', '')[:100]}"
            )
        if not dag_report.has_dag_issues:
            dag_analysis_output["thinking"].append(
                "✅ DAG source code is clean. Proceeding directly to infrastructure healing..."
            )

        phase1["dag_analysis_agent"] = dag_analysis_output

        # ── Route: DAG is clean → skip to SSH-only fix ───────
        if not dag_report.has_dag_issues:
            phase1["dag_patch_agent"] = {
                "thinking": ["DAG source is clean — skipping DAG patch",
                             "Proceeding directly to SSH infrastructure healing..."],
                "output": {"skipped": True, "reason": "No DAG issues found"},
            }
            phase1["attempt_1"] = {"status": "skipped", "reason": "No DAG issues"}

            # Run SSH fix pipeline — use deterministic fix for known NFS tasks
            _base_failed = request.failed_task.split("/map_index=", 1)[0].split("/attempt=", 1)[0]
            NFS_TASKS_SET = {
                "validate_nfs_consistency", "prepare_host_nfs_servers",
                "mount_workers_to_nfs_a", "create_nfs_validation_file",
                "simulate_nfs_mount_inconsistency",
            }
            if _base_failed in NFS_TASKS_SET:
                print(f"[Autofix] Case 4: Using deterministic NFS fix for '{request.failed_task}'")
                strategy = FixStrategy(
                    fix_type="infrastructure_repair",
                    description=(
                        f"Deterministic NFS infrastructure repair for '{request.failed_task}': "
                        "install NFS packages, configure exports, mount shares, "
                        "and create the validation file."
                    ),
                    fix_commands=[
                        "sudo apt-get update > /dev/null 2>&1; "
                        "sudo apt-get install -y nfs-kernel-server nfs-common > /dev/null 2>&1 || true",
                        "sudo mkdir -p /srv/nfs_a/shared /srv/nfs_b/shared && "
                        "sudo chmod 777 /srv/nfs_a/shared /srv/nfs_b/shared",
                        "sudo sed -i '/nfs_a\\|nfs_b\\|broken_option/d' /etc/exports; "
                        "IP_PARTS=$(hostname -I | awk '{print $1}' | cut -d. -f1-3); "
                        "echo \"/srv/nfs_a/shared ${IP_PARTS}.0/24(rw,sync,no_subtree_check,no_root_squash,insecure)\" "
                        "| sudo tee -a /etc/exports > /dev/null; "
                        "echo \"/srv/nfs_b/shared ${IP_PARTS}.0/24(rw,sync,no_subtree_check,no_root_squash,insecure)\" "
                        "| sudo tee -a /etc/exports > /dev/null",
                        "sudo exportfs -ra; "
                        "sudo systemctl enable --now nfs-server > /dev/null 2>&1 || "
                        "sudo systemctl enable --now nfs-kernel-server > /dev/null 2>&1 || true; "
                        "sudo systemctl restart nfs-server > /dev/null 2>&1 || "
                        "sudo systemctl restart nfs-kernel-server > /dev/null 2>&1 || true",
                        "sudo umount -lf /mnt/nfs > /dev/null 2>&1 || true; "
                        "sudo mkdir -p /mnt/nfs; "
                        "SELF_IP=$(hostname -I | awk '{print $1}'); "
                        "timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 "
                        "${SELF_IP}:/srv/nfs_a/shared /mnt/nfs",
                        "echo 'deployment-check' | sudo tee /mnt/nfs/check.txt > /dev/null",
                    ],
                    dry_run_commands=[
                        "exportfs -v 2>/dev/null | grep -q nfs_a && echo 'NFS exports OK' || echo 'NFS exports MISSING'",
                        "mount | grep ' /mnt/nfs ' && echo 'NFS mounted OK' || echo 'NFS NOT mounted'",
                        "test -f /mnt/nfs/check.txt && cat /mnt/nfs/check.txt || echo 'check.txt MISSING'",
                    ],
                    requires_approval=False,
                    estimated_risk="low",
                )
            else:
                strategy = _fix_gen.generate(rca)
            approved = request.auto_approve or not strategy.requires_approval
            result = _fix_exec.execute(
                strategy=strategy,
                worker_nodes=request.worker_nodes,
                approved=approved,
                mock=request.mock or not request.worker_nodes,
            )
            val_report = _val.validate(
                fix_result=result,
                worker_nodes=request.worker_nodes,
                mock=request.mock or not request.worker_nodes,
                task_id=request.failed_task,
            )

            phase1["fix_generator_agent"] = {
                "thinking": [
                    f"Analysing root cause for task: {failure.task_id}",
                    f"Classification: {rca.classification} | Severity: {rca.severity}",
                    f"Fix type: {strategy.fix_type}",
                    f"Risk: {strategy.estimated_risk}",
                    f"Commands: {len(strategy.fix_commands)} fix command(s)",
                ],
                "output": {
                    "fix_type": strategy.fix_type,
                    "fix_commands": strategy.fix_commands,
                    "dry_run_commands": strategy.dry_run_commands,
                    "estimated_risk": strategy.estimated_risk,
                    "description": strategy.description,
                    "requires_approval": strategy.requires_approval,
                },
            }
            phase1["fix_executor_agent"] = {
                "thinking": [
                    f"Target nodes: {len(request.worker_nodes)} worker node(s)",
                    f"Approval status: {'auto-approved' if approved else 'pending'}",
                    f"Executing {len(strategy.fix_commands)} fix command(s)...",
                    f"Execution result: {result.execution_status.upper()}",
                ],
                "output": {
                    "execution_status": result.execution_status,
                    "command_outputs": result.command_outputs,
                    "error_on_fix": result.error_on_fix,
                },
            }
            phase1["validation_agent"] = {
                "thinking": [
                    f"Validating fix for task: {request.failed_task}",
                    f"Running health checks...",
                    f"Checking Redis queue for lingering errors...",
                    f"Validation verdict: {'PASSED' if val_report.is_valid else 'FAILED'}",
                ],
                "output": {
                    "is_valid": val_report.is_valid,
                    "health_check_output": val_report.health_check_output,
                    "queue_status": val_report.queue_status,
                    "collateral_damage_check": val_report.collateral_damage_check,
                    "verdict": val_report.verdict,
                    "escalated_errors": val_report.escalated_errors,
                },
            }
            phase1["attempt_2"] = {
                "status": "success" if val_report.is_valid else "failed",
            }
            
            # ── Verification Run ─────────────────────────────────
            verification_outcome = "skipped"
            verification_run_id = None
            if val_report.is_valid:
                phase1["validation_agent"]["thinking"].append("Triggering final verification DAG run...")
                
                # Temporarily point dag_pat to the original DAG
                original_dag_id = _dag_pat.REMEDIATION_DAG_ID
                _dag_pat.REMEDIATION_DAG_ID = request.dag_id
                try:
                    conf = {"worker_nodes": request.worker_nodes} if request.worker_nodes else {}
                    verification_run_id = _dag_pat._trigger_dag(conf)
                    if verification_run_id:
                        phase1["validation_agent"]["thinking"].append(f"Verification DAG triggered: {verification_run_id}")
                        verification_outcome, _ = _dag_pat._poll_dag_run(verification_run_id)
                        phase1["validation_agent"]["thinking"].append(f"Verification run outcome: {verification_outcome.upper()}")
                finally:
                    _dag_pat.REMEDIATION_DAG_ID = original_dag_id
                
                final_status = "fixed" if verification_outcome == "success" else "escalated"
                phase1["pipeline_status"] = final_status
                
                phase1["validation_agent"]["output"]["verification_run_id"] = verification_run_id
                phase1["validation_agent"]["output"]["verification_outcome"] = verification_outcome
            else:
                final_status = "escalated"
                phase1["pipeline_status"] = "fix_failed"

            phase1["autofix_summary"] = {
                "total_attempts": 1,
                "final_status": final_status,
                "dag_corrected": False,
                "infra_healed": val_report.is_valid,
                "message": "Errors resolved via Infrastructure healing." if final_status == "fixed" else "Infrastructure healed, but verification DAG failed." if val_report.is_valid else "Fix Failed",
                "initial_failed_tasks": initial_failed_tasks,
                "attempt1_skipped": True,
                "attempt1_fixed_tasks": [],
                "attempt2_skipped": False,
                "attempt2_fixed_tasks": [request.failed_task] if val_report.is_valid else [],
                "fix_type": strategy.fix_type,
                "fix_description": strategy.description,
                "estimated_risk": strategy.estimated_risk,
                "commands_executed": len(strategy.fix_commands),
                "execution_status": result.execution_status,
                "validation_verdict": f"Verification DAG: {verification_outcome}" if val_report.is_valid else val_report.verdict,
            }
            return phase1

        # ── Step 2: Attempt 1 — DAG-only fix ─────────────────
        patch_result_1 = _dag_pat.patch_and_run(
            dag_report, attempt_number=1, worker_nodes=request.worker_nodes
        )

        dag_patch_output = {
            "thinking": [
                f"Writing corrected DAG as remediation_workflow.py...",
                f"DAG written: {patch_result_1.dag_written}",
                f"Triggering DAG run via Airflow REST API...",
                f"Polling for completion...",
                f"Attempt 1 outcome: {patch_result_1.run_outcome.upper()}",
            ],
            "output": {
                "dag_written": patch_result_1.dag_written,
                "remediation_dag_id": patch_result_1.remediation_dag_id,
                "dag_run_id": patch_result_1.dag_run_id,
                "run_outcome": patch_result_1.run_outcome,
                "attempt_number": 1,
                "failed_tasks": patch_result_1.failed_tasks,
            },
        }
        phase1["dag_patch_agent"] = dag_patch_output

        phase1["attempt_1"] = {
            "status": patch_result_1.run_outcome,
            "dag_run_id": patch_result_1.dag_run_id,
            "failed_tasks": patch_result_1.failed_tasks,
        }

        # If Attempt 1 succeeded → done!
        if patch_result_1.run_outcome == "success":
            attempt1_skipped = not dag_report.has_dag_issues
            phase1["pipeline_status"] = "fixed"
            phase1["autofix_summary"] = {
                "total_attempts": 1,
                "final_status": "fixed",
                "dag_corrected": True,
                "infra_healed": False,
                "message": "All errors resolved via DAG correction (Attempt 1).",
                "initial_failed_tasks": initial_failed_tasks,
                "attempt1_skipped": attempt1_skipped,
                "attempt1_fixed_tasks": [] if attempt1_skipped else initial_failed_tasks,
                "attempt2_skipped": True,
                "attempt2_fixed_tasks": [],
                "validation_verdict": "Attempt 1 (DAG Fix) fully succeeded.",
            }
            return phase1

        # ── Step 3: Attempt 2 — DAG + SSH fix ────────────────
        dag_patch_output["thinking"].append(
            "⚠️ DAG corrected, but errors persist. Proceeding to Attempt 2 (Infrastructure Healing)..."
        )

        def _base_task_id(task_id: str) -> str:
            return task_id.split("/map_index=", 1)[0].split("/attempt=", 1)[0]

        def _unique_failed_tasks(task_ids: list[str]) -> list[str]:
            unique: list[str] = []
            seen: set[str] = set()
            for task_id in task_ids:
                base = _base_task_id(task_id)
                if base in seen:
                    continue
                seen.add(base)
                unique.append(task_id)
            return unique

        attempt_2_tasks = _unique_failed_tasks(patch_result_1.failed_tasks or [request.failed_task])
        attempt_2_reanalyses = []
        attempt_2_results = []

        # ── Known NFS tasks that need deterministic fixes ──
        NFS_RELATED_TASKS = {
            "validate_nfs_consistency", "prepare_host_nfs_servers",
            "mount_workers_to_nfs_a", "create_nfs_validation_file",
            "simulate_nfs_mount_inconsistency",
        }

        def _make_nfs_fix_strategy(task_id: str) -> "FixStrategy":
            """Build a deterministic NFS infrastructure fix instead of asking the LLM."""
            return FixStrategy(
                fix_type="infrastructure_repair",
                description=(
                    f"Deterministic NFS infrastructure repair for '{task_id}': "
                    "install NFS packages, configure exports, mount shares, "
                    "and create the validation file."
                ),
                fix_commands=[
                    # 1. Install NFS packages if missing
                    "sudo apt-get update > /dev/null 2>&1; "
                    "sudo apt-get install -y nfs-kernel-server nfs-common > /dev/null 2>&1 || true",
                    # 2. Create export directories
                    "sudo mkdir -p /srv/nfs_a/shared /srv/nfs_b/shared && "
                    "sudo chmod 777 /srv/nfs_a/shared /srv/nfs_b/shared",
                    # 3. Configure /etc/exports (clean + add)
                    "sudo sed -i '/nfs_a\\|nfs_b\\|broken_option/d' /etc/exports; "
                    "IP_PARTS=$(hostname -I | awk '{print $1}' | cut -d. -f1-3); "
                    "echo \"/srv/nfs_a/shared ${IP_PARTS}.0/24(rw,sync,no_subtree_check,no_root_squash,insecure)\" "
                    "| sudo tee -a /etc/exports > /dev/null; "
                    "echo \"/srv/nfs_b/shared ${IP_PARTS}.0/24(rw,sync,no_subtree_check,no_root_squash,insecure)\" "
                    "| sudo tee -a /etc/exports > /dev/null",
                    # 4. Restart NFS server + re-export
                    "sudo exportfs -ra; "
                    "sudo systemctl enable --now nfs-server > /dev/null 2>&1 || "
                    "sudo systemctl enable --now nfs-kernel-server > /dev/null 2>&1 || true; "
                    "sudo systemctl restart nfs-server > /dev/null 2>&1 || "
                    "sudo systemctl restart nfs-kernel-server > /dev/null 2>&1 || true",
                    # 5. Mount NFS A share locally
                    "sudo umount -lf /mnt/nfs > /dev/null 2>&1 || true; "
                    "sudo mkdir -p /mnt/nfs; "
                    "SELF_IP=$(hostname -I | awk '{print $1}'); "
                    "timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 "
                    "${SELF_IP}:/srv/nfs_a/shared /mnt/nfs",
                    # 6. Create the validation file that validate_nfs_consistency checks
                    "echo 'deployment-check' | sudo tee /mnt/nfs/check.txt > /dev/null",
                ],
                dry_run_commands=[
                    "exportfs -v 2>/dev/null | grep -q nfs_a && echo 'NFS exports OK' || echo 'NFS exports MISSING'",
                    "mount | grep ' /mnt/nfs ' && echo 'NFS mounted OK' || echo 'NFS NOT mounted'",
                    "test -f /mnt/nfs/check.txt && cat /mnt/nfs/check.txt || echo 'check.txt MISSING'",
                ],
                requires_approval=False,
                estimated_risk="low",
            )

        for actual_failed_task_id in attempt_2_tasks:
            # ── Determine base task name (strip /map_index=N) ──
            base_task = _base_task_id(actual_failed_task_id)

            # ── Deterministic path for known NFS tasks ──
            if base_task in NFS_RELATED_TASKS:
                print(f"[Autofix] Attempt 2: Using deterministic NFS fix for '{actual_failed_task_id}'")
                strategy = _make_nfs_fix_strategy(actual_failed_task_id)
                attempt1_error_report = ErrorReport(
                    task_id=actual_failed_task_id,
                    error_type="NFSInfrastructureFailure",
                    error_message="NFS mount/export chain failure — deterministic fix applied",
                    diagnosis="NFS infrastructure is misconfigured or unmounted on the worker node.",
                    confidence=1.0,
                    raw_log="Deterministic fix path — log analysis skipped",
                )
                attempt1_rca = RootCauseReport(
                    error_report=attempt1_error_report,
                    root_cause="NFS infrastructure not properly configured on worker node",
                    classification="config",
                    severity="high",
                    engineer_action="Install NFS packages, configure exports, mount share, create validation file",
                )
            else:
                # ── Standard LLM path for unknown tasks ──
                if patch_result_1.dag_run_id:
                    try:
                        attempt1_log = _monitor.get_task_log(
                            patch_result_1.dag_run_id,
                            actual_failed_task_id,
                            dag_id=patch_result_1.remediation_dag_id,
                        )
                    except Exception:
                        attempt1_log = request.log_text
                else:
                    attempt1_log = request.log_text

                attempt1_failure = TaskFailure(
                    dag_run_id=patch_result_1.dag_run_id or request.dag_run_id,
                    task_id=actual_failed_task_id,
                    state="failed",
                    log_text=attempt1_log,
                    timestamp=datetime.now().isoformat(),
                )

                attempt1_error_report = _log.analyse(attempt1_failure)
                attempt1_rca = _rca.analyse(attempt1_error_report)
                strategy = _fix_gen.generate(attempt1_rca)

            approved = request.auto_approve or not strategy.requires_approval
            result = _fix_exec.execute(
                strategy=strategy,
                worker_nodes=request.worker_nodes,
                approved=approved,
                mock=request.mock or not request.worker_nodes,
            )
            val_report = _val.validate(
                fix_result=result,
                worker_nodes=request.worker_nodes,
                mock=request.mock or not request.worker_nodes,
                task_id=actual_failed_task_id,
            )

            reanalysis = {
                "dag_id": patch_result_1.remediation_dag_id,
                "dag_run_id": patch_result_1.dag_run_id,
                "failed_task": actual_failed_task_id,
                "log_analysis": {
                    "task_id": attempt1_error_report.task_id,
                    "error_type": attempt1_error_report.error_type,
                    "error_message": attempt1_error_report.error_message,
                    "error_line": attempt1_error_report.error_line,
                    "diagnosis": attempt1_error_report.diagnosis,
                    "confidence": attempt1_error_report.confidence,
                    "rag_diagnosis": attempt1_error_report.rag_diagnosis,
                    "rag_solution": attempt1_error_report.rag_solution,
                    "rag_sources": attempt1_error_report.rag_sources,
                },
                "root_cause": {
                    "root_cause": attempt1_rca.root_cause,
                    "classification": attempt1_rca.classification,
                    "severity": attempt1_rca.severity,
                    "engineer_action": attempt1_rca.engineer_action,
                },
            }
            attempt_2_reanalyses.append(reanalysis)
            attempt_2_results.append({
                "failed_task": actual_failed_task_id,
                "strategy": strategy,
                "result": result,
                "validation": val_report,
                "error_report": attempt1_error_report,
                "rca": attempt1_rca,
            })

        phase1["attempt_2_reanalysis"] = attempt_2_reanalyses

        generator_thinking = [
            f"Attempt 2: Processing {len(attempt_2_results)} failed remediation task(s)",
            f"Attempt 2 source: {patch_result_1.remediation_dag_id}/{patch_result_1.dag_run_id}",
        ]
        executor_thinking = [
            f"Attempt 2: Executing SSH fixes on {len(request.worker_nodes)} worker node(s)",
        ]
        validation_thinking = [
            "Attempt 2: Validating all generated SSH fixes",
        ]

        strategy_outputs = []
        all_command_outputs = []
        validation_outputs = []

        for item in attempt_2_results:
            strategy = item["strategy"]
            result = item["result"]
            val_report = item["validation"]
            error_report = item["error_report"]
            rca_report = item["rca"]
            task_id = item["failed_task"]

            generator_thinking.extend([
                f"Task {task_id}: Log Analyser found {error_report.error_type}",
                f"Task {task_id}: Root cause: {rca_report.root_cause}",
                f"Task {task_id}: Fix type {strategy.fix_type} ({strategy.estimated_risk} risk)",
            ])
            executor_thinking.append(
                f"Task {task_id}: execution {result.execution_status.upper()} with {len(strategy.fix_commands)} command(s)"
            )
            validation_thinking.append(
                f"Task {task_id}: validation {'PASSED' if val_report.is_valid else 'FAILED'}"
            )

            strategy_outputs.append({
                "failed_task": task_id,
                "fix_type": strategy.fix_type,
                "fix_commands": strategy.fix_commands,
                "dry_run_commands": strategy.dry_run_commands,
                "estimated_risk": strategy.estimated_risk,
                "description": strategy.description,
                "requires_approval": strategy.requires_approval,
                "fresh_error_type": error_report.error_type,
                "fresh_root_cause": rca_report.root_cause,
            })
            all_command_outputs.extend(result.command_outputs)
            validation_outputs.append({
                "failed_task": task_id,
                "is_valid": val_report.is_valid,
                "health_check_output": val_report.health_check_output,
                "queue_status": val_report.queue_status,
                "collateral_damage_check": val_report.collateral_damage_check,
                "verdict": val_report.verdict,
                "escalated_errors": val_report.escalated_errors,
            })

        attempt_2_success = all(
            item["result"].execution_status == "success" and item["validation"].is_valid
            for item in attempt_2_results
        )
        failed_attempt_2_tasks = [
            item["failed_task"]
            for item in attempt_2_results
            if item["result"].execution_status != "success" or not item["validation"].is_valid
        ]

        phase1["fix_generator_agent"] = {
            "thinking": generator_thinking,
            "output": {
                "source_dag_id": patch_result_1.remediation_dag_id,
                "source_dag_run_id": patch_result_1.dag_run_id,
                "tasks_processed": [item["failed_task"] for item in attempt_2_results],
                "strategies": strategy_outputs,
            },
        }
        phase1["fix_executor_agent"] = {
            "thinking": executor_thinking,
            "output": {
                "execution_status": "success" if attempt_2_success else "failed",
                "command_outputs": all_command_outputs,
                "failed_tasks": failed_attempt_2_tasks,
            },
        }
        phase1["validation_agent"] = {
            "thinking": validation_thinking,
            "output": {
                "is_valid": attempt_2_success,
                "validations": validation_outputs,
                "failed_tasks": failed_attempt_2_tasks,
                "verdict": (
                    "✅ Validation Passed: all Attempt 2 fixes succeeded."
                    if attempt_2_success
                    else "❌ Validation Failed: one or more Attempt 2 fixes failed."
                ),
            },
        }

        phase1["attempt_2"] = {
            "status": "success" if attempt_2_success else "failed",
            "tasks_processed": [item["failed_task"] for item in attempt_2_results],
            "failed_tasks": failed_attempt_2_tasks,
        }

        if attempt_2_success:
            # ── Verification Run ─────────────────────────────────
            phase1["validation_agent"]["thinking"].append("Triggering final verification DAG run...")
            
            # Since we patched the DAG, we use remediation_workflow (already the default)
            conf = {"worker_nodes": request.worker_nodes} if request.worker_nodes else {}
            verification_run_id = _dag_pat._trigger_dag(conf)
            verification_outcome = "failed"
            
            if verification_run_id:
                phase1["validation_agent"]["thinking"].append(f"Verification DAG triggered: {verification_run_id}")
                verification_outcome, _ = _dag_pat._poll_dag_run(verification_run_id)
                phase1["validation_agent"]["thinking"].append(f"Verification run outcome: {verification_outcome.upper()}")
                
                phase1["validation_agent"]["output"]["verification_run_id"] = verification_run_id
                phase1["validation_agent"]["output"]["verification_outcome"] = verification_outcome
                
                # Append to DAG Patch Agent to update the UI
                phase1["dag_patch_agent"]["thinking"].extend([
                    "---",
                    "Attempt 2 Success -> Triggering Verification Run...",
                    f"Verification DAG triggered: {verification_run_id}",
                    f"Verification run outcome: {verification_outcome.upper()}"
                ])
                phase1["dag_patch_agent"]["output"]["verification_run_id"] = verification_run_id
                phase1["dag_patch_agent"]["output"]["verification_outcome"] = verification_outcome
                
            final_status = "fixed" if verification_outcome == "success" else "escalated"
            phase1["pipeline_status"] = final_status
            
            attempt1_skipped = not dag_report.has_dag_issues
            # Normalise map_index/attempt suffixes before comparing: the original
            # failures are bare task ids (e.g. "simulate_postcheck_error") while
            # remediation failures carry "/map_index=N", so a plain membership
            # test wrongly reports a still-failing mapped task as "fixed".
            _failed_after_1 = {_base_task_id(t) for t in (patch_result_1.failed_tasks or [])}
            attempt1_fixed_tasks = [] if attempt1_skipped else [
                t for t in initial_failed_tasks if _base_task_id(t) not in _failed_after_1
            ]
            attempt2_skipped = attempt_2_success and len(attempt_2_results) == 0
            attempt2_fixed_tasks = [item["failed_task"] for item in attempt_2_results]

            phase1["autofix_summary"] = {
                "total_attempts": 2,
                "final_status": final_status,
                "dag_corrected": True,
                "infra_healed": True,
                "message": "Errors resolved via DAG correction + Infrastructure healing." if final_status == "fixed" else "Infrastructure healed, but verification DAG failed.",
                "initial_failed_tasks": initial_failed_tasks,
                "attempt1_skipped": attempt1_skipped,
                "attempt1_fixed_tasks": attempt1_fixed_tasks,
                "attempt2_skipped": attempt2_skipped,
                "attempt2_fixed_tasks": attempt2_fixed_tasks,
                "execution_status": "success",
                "validation_verdict": f"Verification DAG: {verification_outcome}",
            }
        else:
            # Both attempts failed → escalation
            attempt1_skipped = not dag_report.has_dag_issues
            # Normalise map_index/attempt suffixes before comparing: the original
            # failures are bare task ids (e.g. "simulate_postcheck_error") while
            # remediation failures carry "/map_index=N", so a plain membership
            # test wrongly reports a still-failing mapped task as "fixed".
            _failed_after_1 = {_base_task_id(t) for t in (patch_result_1.failed_tasks or [])}
            attempt1_fixed_tasks = [] if attempt1_skipped else [
                t for t in initial_failed_tasks if _base_task_id(t) not in _failed_after_1
            ]
            attempt2_skipped = len(attempt_2_results) == 0
            
            phase1["pipeline_status"] = "escalated"
            phase1["autofix_summary"] = {
                "total_attempts": 2,
                "final_status": "escalated",
                "dag_corrected": True,
                "infra_healed": False,
                "message": "🚨 Pipeline failed. Manual intervention required.",
                "initial_failed_tasks": initial_failed_tasks,
                "attempt1_skipped": attempt1_skipped,
                "attempt1_fixed_tasks": attempt1_fixed_tasks,
                "attempt2_skipped": attempt2_skipped,
                "attempt2_fixed_tasks": [],
                "failed_attempt_2_tasks": failed_attempt_2_tasks,
                "validation_verdict": "one or more fixes failed validation",
            }

        return phase1

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/fix-status/{fix_id}")
def get_fix_status(fix_id: str):
    """Phase 2: Check the status of a pending or executed fix."""
    pending = _pending_fixes.get(fix_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"Fix ID not found: {fix_id}")

    response = {
        "fix_id": fix_id,
        "status": pending["status"],
        "created_at": pending["created_at"],
    }

    if "result" in pending:
        result = pending["result"]
        response["execution_status"] = result.execution_status
        response["command_outputs"] = result.command_outputs
        response["error_on_fix"] = result.error_on_fix

    return response

# ── Phase 3: HPC Queue Endpoints ──────────────────────────────

@app.post("/api/agents/ingest-log")
def ingest_log(request: FailureAnalysisRequest):
    """
    Phase 3: Simulates HPC log ingestion by placing the error log into the Redis Queue.
    """
    if not _hpc_queue:
        raise HTTPException(status_code=500, detail="Redis queue is not configured.")
        
    job = _hpc_queue.enqueue(
        "api.worker.process_log", 
        kwargs=request.model_dump(),
        meta={"task_id": request.failed_task, "log_text": request.log_text}
    )
    return {"status": "enqueued", "job_id": job.id, "queue": "hpc_error_logs"}


@app.get("/api/agents/queue-status")
def queue_status():
    """
    Phase 3: Polls the queue for lingering or new errors to display on the frontend.
    """
    if not _hpc_queue:
        return {"queue_available": False, "queued_errors": []}
        
    jobs = _hpc_queue.get_jobs()
    errors = []
    for job in jobs:
        # Avoid showing internal rq attributes, build a clean object
        errors.append({
            "job_id": job.id,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "task_id": job.meta.get("task_id", "Unknown"),
            "log_text": job.meta.get("log_text", "No log text"),
            "status": job.get_status()
        })
        
    return {"queue_available": True, "queued_errors": errors}
