# agents/workflow_graph.py
import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from agents.run_workflow_agent     import RunWorkflowAgent
from agents.monitor_workflow_agent import MonitorWorkflowAgent
from agents.log_analyser_agent     import LogAnalyserAgent
from agents.root_cause_agent       import RootCauseAgent
from agents.alerting_agent         import AlertingAgent
from common.models                 import (DeploymentConfig, TaskFailure,
                                           ErrorReport, RootCauseReport,
                                           AlertResult)

# Instantiate agents
_run      = RunWorkflowAgent()
_monitor  = MonitorWorkflowAgent()
_log      = LogAnalyserAgent()
_rca      = RootCauseAgent()
_alert    = AlertingAgent()


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

    # Control flags
    failure_detected  : bool
    pipeline_status   : str              # running / success / failed / alerted


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

    # Entry point
    graph.set_entry_point("run_workflow")

    # Fixed edges
    graph.add_edge("run_workflow", "monitor")
    graph.add_edge("log_analyser", "root_cause")

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

    # Terminal edges
    graph.add_edge("success",  END)
    graph.add_edge("log_only", END)
    graph.add_edge("alert",    END)

    return graph.compile()


# RUNNER


def run_graph(deployment_config: DeploymentConfig,
              sample_log_path: str = "") -> PipelineState:
    """
    Run the full LangGraph pipeline.
    sample_log_path: provide path for mock mode, empty string for real Airflow.
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
        "failure_detected"  : False,
        "pipeline_status"   : "pending"
    }

    final_state = graph.invoke(initial_state)
    return final_state
