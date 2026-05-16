# agents/workflow_graph.py
import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

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
                                           AlertResult, FixStrategy,
                                           FixResult, ValidationReport,
                                           DagAnalysisReport, DagPatchResult)

# Instantiate agents
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


# STATE — shared data passed between all nodes

class PipelineState(TypedDict):
    # Input
    deployment_config : DeploymentConfig
    sample_log_path   : str              # empty string for real mode

    # Populated as pipeline runs
    dag_run_id        : Optional[str]
    task_failure      : Optional[TaskFailure]
    error_report      : Optional[ErrorReport]
    rca_report        : Optional[RootCauseReport]
    alert_result      : Optional[AlertResult]

    # Phase 2: Autofix fields
    fix_strategy      : Optional[FixStrategy]
    fix_result        : Optional[FixResult]
    validation_report : Optional[ValidationReport]
    autofix_enabled   : bool             # whether to attempt autofix
    worker_nodes      : list             # list of dicts with ip/username/password
    retry_count       : int              # current retry attempt
    max_retries       : int              # max retry attempts (default: 2)

    # Phase 2 Hybrid: DAG correction fields
    dag_analysis_report : Optional[DagAnalysisReport]
    dag_patch_result    : Optional[DagPatchResult]
    current_attempt     : int              # 1 or 2

    # Control flags
    failure_detected  : bool
    pipeline_status   : str              # running / success / failed / alerted / fixing / fixed


# NODES — one function per agent

def node_run_workflow(state: PipelineState) -> PipelineState:
    print("\n[Graph] ▶ Node: Run Workflow Agent")
    config = state["deployment_config"]

    run_id = _run.trigger_dag_mock(config) if state["sample_log_path"] \
             else _run.trigger_dag(config)

    state["dag_run_id"]       = run_id
    state["pipeline_status"]  = "running" if run_id else "failed"
    return state


def node_monitor_workflow(state: PipelineState) -> PipelineState:
    print("\n[Graph] 👁 Node: Monitor Workflow Agent")

    if state["pipeline_status"] == "failed":
        print("[Graph] Skipping monitor — DAG trigger failed")
        return state

    run_id   = state["dag_run_id"]
    log_path = state["sample_log_path"]

    failure = _monitor.monitor_mock(run_id, log_path) if log_path \
              else _monitor.monitor(run_id)

    state["task_failure"]      = failure
    state["failure_detected"]  = failure is not None
    state["pipeline_status"]   = "failed" if failure else "success"
    return state


def node_log_analyser(state: PipelineState) -> PipelineState:
    print("\n[Graph] 🔍 Node: Log Analyser Agent")
    failure            = state["task_failure"]
    state["error_report"] = _log.analyse(failure)
    return state


def node_root_cause(state: PipelineState) -> PipelineState:
    print("\n[Graph] 🧠 Node: Root Cause Agent")
    error_report      = state["error_report"]
    state["rca_report"] = _rca.analyse(error_report)
    return state


def node_alert(state: PipelineState) -> PipelineState:
    print("\n[Graph] 📣 Node: Alerting Agent")
    rca                   = state["rca_report"]
    state["alert_result"] = _alert.alert(rca)
    state["pipeline_status"] = "alerted"
    return state


def node_success(state: PipelineState) -> PipelineState:
    print("\n[Graph] ✅ Node: Deployment Successful — no agent intervention needed")
    state["pipeline_status"] = "success"
    return state


def node_log_only(state: PipelineState) -> PipelineState:
    print("\n[Graph] ℹ️  Node: Low severity — logged only, no alert sent")
    rca = state["rca_report"]
    print(f"  Task     : {rca.error_report.task_id}")
    print(f"  Cause    : {rca.root_cause}")
    print(f"  Severity : LOW")
    state["pipeline_status"] = "alerted"
    return state


# ── Phase 2: Autofix nodes ───────────────────────────────────

def node_dag_analysis(state: PipelineState) -> PipelineState:
    print("\n[Graph] 🔍 Node: DAG Analysis Agent")
    report = _dag_ana.analyse("deployment_workflow.py")
    state["dag_analysis_report"] = report
    if report.has_dag_issues:
        print(f"  Found {len(report.issues)} DAG issue(s) — will attempt DAG patch")
    else:
        print("  DAG source is clean — will proceed to SSH healing")
    return state


def node_dag_patch(state: PipelineState) -> PipelineState:
    print("\n[Graph] 📝 Node: DAG Patch Agent")
    analysis = state["dag_analysis_report"]
    attempt = state.get("current_attempt", 1)
    worker_nodes = state.get("worker_nodes", [])
    result = _dag_pat.patch_and_run(analysis, attempt_number=attempt, worker_nodes=worker_nodes)
    state["dag_patch_result"] = result
    if result.run_outcome == "success":
        state["pipeline_status"] = "fixed"
    else:
        state["pipeline_status"] = "dag_fix_failed"
    return state


def node_fix_generator(state: PipelineState) -> PipelineState:
    print("\n[Graph] 🔧 Node: Fix Generator Agent")
    rca = state["rca_report"]
    strategy = _fix_gen.generate(rca)
    state["fix_strategy"] = strategy
    state["pipeline_status"] = "fixing"
    return state


def node_fix_executor(state: PipelineState) -> PipelineState:
    print("\n[Graph] ⚡ Node: Fix Executor Agent")
    strategy     = state["fix_strategy"]
    worker_nodes = state.get("worker_nodes", [])
    is_mock      = bool(state["sample_log_path"])

    # For low/medium risk, auto-approve
    approved = not strategy.requires_approval or strategy.estimated_risk in ("low", "medium")

    result = _fix_exec.execute(
        strategy=strategy,
        worker_nodes=worker_nodes,
        approved=approved,
        mock=is_mock,
    )

    # Track attempt number
    result.attempt_number = state.get("retry_count", 0) + 1
    result.max_attempts = state.get("max_retries", 2)

    state["fix_result"] = result
    return state


def node_validation_agent(state: PipelineState) -> PipelineState:
    print("\n[Graph] 🔬 Node: Validation Agent")
    fix_result = state.get("fix_result")
    
    if not fix_result or fix_result.execution_status != "success":
        print("  Skipping validation due to failed or pending fix execution.")
        return state

    worker_nodes = state.get("worker_nodes", [])
    is_mock = bool(state.get("sample_log_path"))
    task_id = state.get("task_failure").task_id if state.get("task_failure") else ""

    report = _val.validate(
        fix_result=fix_result,
        worker_nodes=worker_nodes,
        mock=is_mock,
        task_id=task_id
    )

    state["validation_report"] = report
    if not report.is_valid:
        state["pipeline_status"] = "validation_failed"
        
    return state


def node_retry_check(state: PipelineState) -> PipelineState:
    """
    After fix execution — decide whether to retry the DAG
    or give up. Increments retry_count.
    """
    print("\n[Graph] 🔄 Node: Retry Check")
    fix_result = state["fix_result"]

    if fix_result.execution_status == "success":
        report = state.get("validation_report")
        if report and report.is_valid:
            state["retry_count"] = state.get("retry_count", 0) + 1
            print(f"  Fix applied and validated successfully — will retry DAG "
                  f"(attempt {state['retry_count']}/{state['max_retries']})")
            state["pipeline_status"] = "retrying"
        else:
            print("  Fix execution succeeded but validation failed.")
            state["pipeline_status"] = "validation_failed"
    elif fix_result.execution_status == "pending_approval":
        print("  Fix requires approval — pausing pipeline")
        state["pipeline_status"] = "pending_approval"
    else:
        print(f"  Fix execution failed: {fix_result.error_on_fix}")
        state["pipeline_status"] = "fix_failed"

    return state


# CONDITIONAL EDGES — routing logic

def route_after_monitor(state: PipelineState) -> str:
    """After monitoring — did anything fail?"""
    if not state["failure_detected"]:
        return "success"           # → node_success → END
    return "log_analyser"          # → node_log_analyser


def route_after_rca(state: PipelineState) -> str:
    """After root cause analysis — how severe is it?"""
    severity = state["rca_report"].severity.lower()
    if severity == "low":
        return "log_only"          # → node_log_only → END
    return "alert"                 # → node_alert → END (high or critical)


def route_after_alert(state: PipelineState) -> str:
    """After alerting — should we attempt autofix?"""
    if not state.get("autofix_enabled", False):
        return "end"               # → END (Phase 1 behaviour)

    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    if retry_count >= max_retries:
        print(f"[Graph] ⛔ Max retries ({max_retries}) reached — giving up")
        return "end"

    return "dag_analysis"          # → Phase 2 hybrid: analyse DAG first


def route_after_dag_analysis(state: PipelineState) -> str:
    """After DAG analysis — is the DAG broken or clean?"""
    report = state.get("dag_analysis_report")
    if report and report.has_dag_issues:
        return "dag_patch"         # → attempt DAG correction first
    return "fix_generator"         # → DAG is clean, go directly to SSH fix


def route_after_dag_patch(state: PipelineState) -> str:
    """After DAG patch — did the remediation DAG succeed?"""
    result = state.get("dag_patch_result")
    if result and result.run_outcome == "success":
        return "end"               # → DAG fix worked, done!
    # DAG fix failed — escalate to SSH healing
    print("[Graph] ⚠️  DAG correction alone did not resolve all errors — escalating to SSH healing")
    state["current_attempt"] = 2
    return "fix_generator"         # → Attempt 2: SSH infrastructure fix


def route_after_retry_check(state: PipelineState) -> str:
    """After retry check — what next?"""
    status = state["pipeline_status"]

    if status == "retrying":
        return "run_workflow"      # loop back to re-run DAG
    if status == "pending_approval":
        return "end"               # pause and wait for human
    return "end"                   # fix failed — give up


# GRAPH — wire everything together

def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("run_workflow",  node_run_workflow)
    graph.add_node("monitor",       node_monitor_workflow)
    graph.add_node("log_analyser",  node_log_analyser)
    graph.add_node("root_cause",    node_root_cause)
    graph.add_node("alert",         node_alert)
    graph.add_node("success",       node_success)
    graph.add_node("log_only",      node_log_only)
    # Phase 2 Hybrid nodes
    graph.add_node("dag_analysis",  node_dag_analysis)
    graph.add_node("dag_patch",     node_dag_patch)
    graph.add_node("fix_generator", node_fix_generator)
    graph.add_node("fix_executor",  node_fix_executor)
    graph.add_node("validation_agent", node_validation_agent)
    graph.add_node("retry_check",   node_retry_check)

    # Entry point
    graph.set_entry_point("run_workflow")

    # Fixed edges
    graph.add_edge("run_workflow", "monitor")
    graph.add_edge("log_analyser", "root_cause")
    # Phase 2 fixed edges
    graph.add_edge("fix_generator", "fix_executor")
    graph.add_edge("fix_executor",  "validation_agent")
    graph.add_edge("validation_agent", "retry_check")

    # Conditional edges
    graph.add_conditional_edges(
        "monitor",
        route_after_monitor,
        {
            "success"      : "success",
            "log_analyser" : "log_analyser"
        }
    )

    graph.add_conditional_edges(
        "root_cause",
        route_after_rca,
        {
            "log_only" : "log_only",
            "alert"    : "alert"
        }
    )

    # Phase 2 Hybrid: after alerting, route to DAG analysis first
    graph.add_conditional_edges(
        "alert",
        route_after_alert,
        {
            "end"           : END,
            "dag_analysis"  : "dag_analysis"
        }
    )

    # After DAG analysis: patch or go directly to SSH
    graph.add_conditional_edges(
        "dag_analysis",
        route_after_dag_analysis,
        {
            "dag_patch"     : "dag_patch",
            "fix_generator" : "fix_generator"
        }
    )

    # After DAG patch: done or escalate to SSH
    graph.add_conditional_edges(
        "dag_patch",
        route_after_dag_patch,
        {
            "end"           : END,
            "fix_generator" : "fix_generator"
        }
    )

    # Phase 2: after retry check, loop back or end
    graph.add_conditional_edges(
        "retry_check",
        route_after_retry_check,
        {
            "run_workflow" : "run_workflow",
            "end"          : END
        }
    )

    # Terminal edges
    graph.add_edge("success",  END)
    graph.add_edge("log_only", END)

    return graph.compile()


# RUNNER


def run_graph(deployment_config: DeploymentConfig,
              sample_log_path: str = "",
              autofix_enabled: bool = False,
              worker_nodes: list | None = None,
              max_retries: int = 2) -> PipelineState:
    """
    Run the full LangGraph pipeline.
    sample_log_path: provide path for mock mode, empty string for real Airflow.
    autofix_enabled: if True, Phase 2 autofix loop is active.
    worker_nodes:    list of dicts with ip/username/password for SSH fixes.
    max_retries:     max autofix + retry cycles before giving up.
    """
    graph = build_graph()

    initial_state: PipelineState = {
        "deployment_config" : deployment_config,
        "sample_log_path"   : sample_log_path,
        "dag_run_id"        : None,
        "task_failure"      : None,
        "error_report"      : None,
        "rca_report"        : None,
        "alert_result"      : None,
        "fix_strategy"      : None,
        "fix_result"        : None,
        "validation_report" : None,
        "autofix_enabled"   : autofix_enabled,
        "worker_nodes"      : worker_nodes or [],
        "retry_count"       : 0,
        "max_retries"       : max_retries,
        "dag_analysis_report" : None,
        "dag_patch_result"    : None,
        "current_attempt"     : 1,
        "failure_detected"  : False,
        "pipeline_status"   : "pending"
    }

    final_state = graph.invoke(initial_state)
    return final_state
