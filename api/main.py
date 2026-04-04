# api/main.py
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
from common.models                 import (DeploymentConfig, TaskFailure,
                                           ErrorReport, RootCauseReport)

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
_run     = RunWorkflowAgent()
_monitor = MonitorWorkflowAgent()
_log     = LogAnalyserAgent()
_rca     = RootCauseAgent()
_alert   = AlertingAgent()



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

    error_report = _log.analyse(failure)

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

    rca = _rca.analyse(error_report)

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

    alert_result = _alert.alert(rca)

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
