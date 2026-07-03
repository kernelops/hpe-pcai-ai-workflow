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

MAX_FIX_ITERATIONS = 5   # hard cap on ping-pong rounds

try:
    from redis import Redis
    from rq import Queue
    _redis_conn = Redis(host="localhost", port=6379, db=0)
    _hpc_queue = Queue("hpc_error_logs", connection=_redis_conn)
except ImportError:
    _redis_conn = None
    _hpc_queue = None
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

# In-memory store for pending fix approvals
_pending_fixes: dict[str, dict] = {}
_analysis_cache: dict[str, dict] ={}

# REQUEST SCHEMA

class PipelineRequest(BaseModel):
    dag_id          : str = "pcai_deployment"
    node_ips        : list[str] = ["10.0.0.1"]
    os_version      : str = "ubuntu22.04"
    spp_version     : str = "2025.03"
    storage_config  : dict = {}
    sample_log_path : Optional[str] = None   # empty = real Airflow mode


class FailureAnalysisRequest(BaseModel):
    dag_id      : str = "minio_health_check"  #minio_health_check
    dag_run_id  : str
    failed_task : str
    task_state  : str = "failed"
    log_text    : str
    timestamp   : str


def _build_failure_analysis_response(
    dag_id: str,
    dag_run_id: str,
    failure: TaskFailure,
    
):
    workflow_agent_output = {
        "thinking": [
            f"Failed DAG ID: {dag_id}",
            f"Failed DAG Run ID: {dag_run_id}",
            f"Failed Task ID: {failure.task_id}",
        ],
        "output": {
            "dag_id": dag_id,
            "dag_run_id": dag_run_id,
            "status": "existing-run",
            "run_path": dag_id,
            "failed_task": failure.task_id,
        },
    }

    monitor_agent_output = {
        "thinking": [
            f"Received failure context for DAG run: {dag_run_id}",
            f"Failure confirmed in task: {failure.task_id}",
        ],
        "output": {
            "failure_detected": True,
            "failed_task": failure.task_id,
            "task_state": failure.state,
            "breakpoint": failure.task_id,
        },
    }

    error_report = _log.analyse(failure)
    print("ERROR REPORT FROM LOG ANALYSER AGENT:\n", error_report)

    log_analysis_agent_output = {
        "thinking": [
            "Building Log Analyser Agent output (with RAG)...",
        ],
        "output": {
            "task_id": error_report.task_id,
            "error_type": error_report.error_type,
            "error_message": error_report.error_message,
            "error_line": error_report.error_line,
            "diagnosis": error_report.diagnosis,
            "confidence": error_report.confidence,
            "command_that_failed": error_report.command_that_failed,
            "rag_diagnosis": error_report.rag_diagnosis,
            "rag_solution": error_report.rag_solution,
            "rag_prevention": error_report.rag_prevention,
            "rag_sources": error_report.rag_sources,
        },
    }

    rca = _rca.analyse(error_report)
    print("RCA REPORT FROM ROOT CAUSE AGENT:\n", rca)

    root_cause_agent_output = {
        "thinking": [
            "Building Root Cause Agent output...",

        ],
        "output": {
            "root_cause": rca.root_cause,
            "classification": rca.classification,
            "severity": rca.severity,
            "engineer_action": rca.engineer_action,
        },
    }

    alert_result = _alert.alert(rca)
    print("ALERT RESULT FROM ALERTING AGENT\n", alert_result)

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

    result = {
        "pipeline_status": "alerted",
        "dag_run_id": dag_run_id,
        "failure_detected": True,
        "workflow_agent": workflow_agent_output,
        "monitor_agent": monitor_agent_output,
        "log_analysis_agent": log_analysis_agent_output,
        "root_cause_agent": root_cause_agent_output,
        "alerting_agent": alerting_agent_output,
        "combined_summary": combined_summary,
        "error_report": error_report,
        "rca": rca,
        "alert_result": alert_result,
    }
    _analysis_cache[dag_run_id] = result
    return result

def _run_fix_loop(
    rca: RootCauseReport,
    worker_nodes: list[dict],
    mock: bool = False,
) -> tuple[FixStrategy, FixResult]:
    """
    Runs the RAG-based fix loop.
    Flow:
      1. FixExecutor runs RAG diagnostics
      2. FixGenerator analyzes results → selects fix index
      3. FixExecutor executes the selected fix commands
      4. FixGenerator re-evaluates → selects next fix or done
      5. Loop continues until fixed or max 5 iterations
    """
    command_history: list[dict] = []
    final_reasoning = ""
    estimated_risk = "medium"
    MAX_ITERATIONS = 5

    task_id = rca.error_report.task_id
    raw_log = rca.error_report.raw_log
    
    print(f"\n[FixLoop] Starting RAG-based fix loop for: {task_id}")
    print(f"[FixLoop] Worker nodes: {len(worker_nodes)}")
    
    # ── Step 1: Run RAG diagnostics ─────────────────────────
    print(f"\n[FixLoop] 🔍 Step 1: RAG Diagnostics")
    print("-" * 40)
    
    rag_entry, diagnostic_results = _fix_exec.execute_rag_diagnostics(
        task_id=task_id,
        raw_log=raw_log,
        worker_nodes=worker_nodes,
        mock=False
    )
    
    if not rag_entry or not diagnostic_results:
        print("[FixLoop] ❌ RAG diagnostics failed or no match found")
        # Return empty strategy
        strategy = _fix_gen.build_fix_strategy(
            rca=rca,
            command_history=[],
            final_reasoning="No RAG match found for this error",
            estimated_risk="high"
        )
        result = _fix_exec.build_fix_result(strategy, [])
        return strategy, result
    
    # Add diagnostic results to history
    command_history.extend(diagnostic_results)
    
    # ── Step 2: Ping-pong loop ──────────────────────────────
    fix_results = []
    selected_indices = []
    
    for iteration in range(MAX_ITERATIONS):
        print(f"\n[FixLoop] 🔄 Iteration {iteration + 1}/{MAX_ITERATIONS}")
        print("-" * 40)
        
        # ── Step 2a: Generator analyzes and selects fix ──────
        if iteration == 0:
            # First iteration: Only diagnostic results
            decision = _fix_gen.get_rag_fix_index(
                task_id=task_id,
                raw_log=raw_log,
                rag_entry=rag_entry,
                diagnostic_results=diagnostic_results,
                fix_results=None  # No fix results yet
            )
        else:
            # Subsequent iterations: Include fix results
            decision = _fix_gen.get_rag_fix_index(
                task_id=task_id,
                raw_log=raw_log,
                rag_entry=rag_entry,
                diagnostic_results=diagnostic_results,
                fix_results=fix_results  # Include previous fix results
            )
        
        selected_index = decision.get("selected_index", -1)
        final_reasoning = decision.get("reasoning", "")
        phase = decision.get("phase", "done")
        
        print(f"[FixLoop] 📝 Selected index: {selected_index}")
        print(f"[FixLoop] 📝 Phase: {phase}")
        
        # ── Step 2b: Check if done ───────────────────────────
        if selected_index == -1 or phase == "done":
            print(f"[FixLoop] ✅ Fix completed: {final_reasoning}")
            break
        
        # ── Step 2c: Execute the selected fix ────────────────
        print(f"[FixLoop] 🔧 Executing fix index: {selected_index}")
        
        fix_results = _fix_exec.execute_rag_fix(
            rag_entry=rag_entry,
            selected_index=selected_index,
            worker_nodes=worker_nodes,
            mock=mock,
        )
        
        if not fix_results:
            print("[FixLoop] ⚠️  No fix results, breaking loop")
            break
        
        # Add fix results to history
        command_history.extend(fix_results)
        selected_indices.append(selected_index)
        
        # Check if fix was successful (all exit codes 0)
        all_success = all(r.get("exit_code", -1) == 0 for r in fix_results)
        if all_success:
            print("[FixLoop] ✅ All fix commands succeeded!")
            # Run verification (re-run diagnostics to confirm)
            print("[FixLoop] 🔍 Running verification...")

            # Re-run diagnostics + original failing command
            verification_commands = [r["command"] for r in diagnostic_results]

            ver_results = _fix_exec.execute_batch(
                commands=verification_commands,
                worker_nodes=worker_nodes,
                phase="verification",
                mock=mock
            )
            command_history.extend(ver_results)
    
    else:
        # Max iterations reached
        print(f"[FixLoop] ⚠️  Max iterations ({MAX_ITERATIONS}) reached")
        final_reasoning = f"Max iterations reached. {len(command_history)} commands executed."
    
    # ── Step 3: Package results ──────────────────────────────
    strategy = _fix_gen.build_fix_strategy(
        rca=rca,
        command_history=command_history,
        final_reasoning=final_reasoning,
        estimated_risk=estimated_risk,
    )
    result = _fix_exec.build_fix_result(
        strategy=strategy,
        command_history=command_history,
    )
    
    print(f"\n[FixLoop] 🏁 Loop complete: {result.execution_status}")
    print(f"[FixLoop] 📊 Total commands: {len(command_history)}")
    
    return strategy, result

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
        if dag_run_id is None:
            raise HTTPException(
                status_code=500, 
                detail="Failed to trigger DAG - no dag_run_id returned"
            )
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

        return _build_failure_analysis_response(config.dag_id, dag_run_id, failure)

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
        return _build_failure_analysis_response(
            dag_id=request.dag_id,
            dag_run_id=request.dag_run_id,
            failure=failure,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 2: Autofix endpoints ───────────────────────────────

class GenerateFixRequest(BaseModel):
    dag_id      : str = "minio_health_check" #minio_health_check
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
    dag_id      : str = "minio_health_check" #minio_health_check
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
        strategy, result = _run_fix_loop(
            rca = rca,
            worker_nodes = request.worker_nodes,
            mock = request.mock or not request.worker_nodes,
        )

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
        ALLOW_PHASE1_JSON =  False
        phase1 = {}

        # Build the base Phase 1 response
        if request.dag_run_id in _analysis_cache:
            print(f"[AutoFixPipeline] Using cached phase 1 results for dag_run_id : {request.dag_run_id}")
            phase1 = _analysis_cache[request.dag_run_id]
        elif ALLOW_PHASE1_JSON:
            print(f"[AutoFixPipeline] No cache found - using phase1.json for dag_run_id : {request.dag_run_id}")
            import json
            with open("api/phase1.json", "r") as f:
                json_data = json.load(f)
            # The JSON key format is {dag_run_id}:{worker_node_ip}
            cache_key = f"{request.dag_run_id}:{request.worker_nodes[0]['ip'] if request.worker_nodes else 'default'}"
            if cache_key in json_data:
                entry = json_data[cache_key]
                print(f"[AutoFixPipeline] Found entry for {cache_key}")
                
                # Build phase1 from the JSON entry
                phase1 = {
                    "pipeline_status": entry.get("pipeline_status", "alerted"),
                    "dag_run_id": entry.get("dag_run_id", request.dag_run_id),
                    "failure_detected": entry.get("failure_detected", True),
                    "workflow_agent": entry.get("workflow_agent", {}),
                    "monitor_agent": entry.get("monitor_agent", {}),
                    "log_analysis_agent": entry.get("log_analysis_agent", {}),
                    "root_cause_agent": entry.get("root_cause_agent", {}),
                    "alerting_agent": entry.get("alerting_agent", {}),
                    "combined_summary": entry.get("combined_summary", {}),
                    # Store the raw objects for later use
                    "error_report": entry.get("error_report", {}),
                    "rca": entry.get("rca", {}),
                    "alert_result": entry.get("alert_result", {})
                }
        else:
            print(f"[AutoFixPiepeline] No cache found - running Phase 1 analysis fresh")
            phase1 = _build_failure_analysis_response(
                dag_id=request.dag_id,
                dag_run_id=request.dag_run_id,
                failure=failure,
            )
        # # ── Step 1: DAG Analysis ─────────────────────────────
        dag_report = _dag_ana.analyse("minio_healthcheck_dag.py")    #minio_health_check

        dag_analysis_output = {
            "thinking": [
                f"Scanning minio_healthcheck_dag.py source code...",   #minio_health_check
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

            # Run existing SSH fix pipeline
            strategy, result = _run_fix_loop(
                rca = phase1["rca"],
                worker_nodes = request.worker_nodes,
                mock = request.mock or not request.worker_nodes,
                )
            approved = request.auto_approve or not strategy.requires_approval
            val_report = _val.validate(
                fix_result=result,
                worker_nodes=request.worker_nodes,
                mock=request.mock or not request.worker_nodes,
                task_id=request.failed_task,
            )

            phase1["fix_generator_agent"] = {
                "thinking": [
                    f"Analysing root cause for task: {failure.task_id}",
                    f"Classification: {phase1["rca"].classification} | Severity: {phase1["rca"].severity}",
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
            phase1["pipeline_status"] = "fixed" if val_report.is_valid else "fix_failed"
            phase1["autofix_summary"] = {
                "total_attempts": 1,
                "final_status": "fixed" if val_report.is_valid else "escalated",
                "dag_corrected": False,
                "infra_healed": val_report.is_valid,
                "fix_type": strategy.fix_type,
                "fix_description": strategy.description,
                "estimated_risk": strategy.estimated_risk,
                "commands_executed": len(strategy.fix_commands),
                "execution_status": result.execution_status,
                "validation_verdict": val_report.verdict,
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
            phase1["pipeline_status"] = "fixed"
            phase1["autofix_summary"] = {
                "total_attempts": 1,
                "final_status": "fixed",
                "dag_corrected": True,
                "infra_healed": False,
                "message": "All errors resolved via DAG correction (Attempt 1).",
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

        for actual_failed_task_id in attempt_2_tasks:
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
            strategy, result = _run_fix_loop(
                rca          = attempt1_rca,
                worker_nodes = request.worker_nodes,
                mock         = request.mock or not request.worker_nodes,
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
            phase1["pipeline_status"] = "fixed"
            phase1["autofix_summary"] = {
                "total_attempts": 2,
                "final_status": "fixed",
                "dag_corrected": True,
                "infra_healed": True,
                "message": "Errors resolved via DAG correction + Infrastructure healing (Attempt 2).",
                "tasks_fixed": [item["failed_task"] for item in attempt_2_results],
                "commands_executed": sum(len(item["strategy"].fix_commands) for item in attempt_2_results),
                "execution_status": "success",
                "validation_verdict": "all fixes validated",
            }
        else:
            # Both attempts failed → escalation
            phase1["pipeline_status"] = "escalated"
            phase1["autofix_summary"] = {
                "total_attempts": 2,
                "final_status": "escalated",
                "dag_corrected": True,
                "infra_healed": False,
                "message": "🚨 Both attempts failed. Manual intervention required.",
                "attempt_1_outcome": patch_result_1.run_outcome,
                "attempt_2_outcome": "failed",
                "failed_attempt_2_tasks": failed_attempt_2_tasks,
                "validation_verdict": "one or more fixes failed validation",
            }

        return phase1

    except Exception as e:
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
