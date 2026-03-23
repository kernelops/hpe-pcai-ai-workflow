# agents/crew_agents.py
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from langchain_groq import ChatGroq

from agents.run_workflow_agent     import RunWorkflowAgent
from agents.monitor_workflow_agent import MonitorWorkflowAgent
from agents.log_analyser_agent     import LogAnalyserAgent
from agents.root_cause_agent       import RootCauseAgent
from agents.alerting_agent         import AlertingAgent
from common.config                 import GROQ_API_KEY, GROQ_MODEL
from common.models                 import (DeploymentConfig, TaskFailure,
                                           ErrorReport, RootCauseReport)

# Shared LLM 
llm = ChatGroq(
    api_key   = GROQ_API_KEY,
    model_name= GROQ_MODEL,
    temperature= 0.1
)

# Instantiate underlying agent logic 
_run_agent      = RunWorkflowAgent()
_monitor_agent  = MonitorWorkflowAgent()
_log_analyser   = LogAnalyserAgent()
_root_cause     = RootCauseAgent()
_alerting       = AlertingAgent()



# TOOLS — wrap existing agent logic as CrewAI tools

@tool("trigger_airflow_dag")
def trigger_airflow_dag_tool(config_json: str) -> str:
    """
    Triggers the Airflow DAG with the given deployment configuration.
    Input: JSON string with keys: dag_id, node_ips, os_version,
           spp_version, storage_config.
    Returns the DAG run ID as a string.
    """
    import json
    data      = json.loads(config_json)
    config    = DeploymentConfig(**data)
    run_id    = _run_agent.trigger_dag_mock(config)
    return run_id or "TRIGGER_FAILED"


@tool("monitor_airflow_dag")
def monitor_airflow_dag_tool(input_json: str) -> str:
    """
    Monitors an Airflow DAG run for task failures or stalls.
    Input: JSON string with keys: dag_run_id, sample_log_path (for mock).
    Returns JSON string of TaskFailure if failure detected, else 'NO_FAILURE'.
    """
    import json
    data        = json.loads(input_json)
    dag_run_id  = data["dag_run_id"]
    log_path    = data.get("sample_log_path", "")

    if log_path:
        failure = _monitor_agent.monitor_mock(dag_run_id, log_path)
    else:
        failure = _monitor_agent.monitor(dag_run_id)

    if not failure:
        return "NO_FAILURE"
    return failure.model_dump_json()


@tool("analyse_task_log")
def analyse_task_log_tool(failure_json: str) -> str:
    """
    Analyses a failed Airflow task log using LLM and optional RAG.
    Input: JSON string of a TaskFailure object.
    Returns JSON string of ErrorReport with error_type, diagnosis, confidence.
    """
    import json
    failure     = TaskFailure(**json.loads(failure_json))
    report      = _log_analyser.analyse(failure)
    return report.model_dump_json()


@tool("find_root_cause")
def find_root_cause_tool(error_report_json: str) -> str:
    """
    Performs root cause analysis on a structured error report.
    Input: JSON string of an ErrorReport object.
    Returns JSON string of RootCauseReport with classification and severity.
    """
    import json
    error_report = ErrorReport(**json.loads(error_report_json))
    rca          = _root_cause.analyse(error_report)
    return rca.model_dump_json()


@tool("send_alert")
def send_alert_tool(rca_json: str) -> str:
    """
    Composes and sends an alert based on root cause analysis.
    Input: JSON string of a RootCauseReport object.
    Returns JSON string of AlertResult with message and channels notified.
    """
    import json
    rca    = RootCauseReport(**json.loads(rca_json))
    result = _alerting.alert(rca)
    return result.model_dump_json()



# CREW AGENTS — formal CrewAI agent definitions

run_workflow_agent = Agent(
    role  = "Deployment Trigger Specialist",
    goal  = (
        "Receive deployment configuration and trigger the Airflow DAG "
        "via REST API. Track and return the DAG run ID for monitoring."
    ),
    backstory = (
        "You are an automation specialist responsible for initiating "
        "HPE PCAI infrastructure deployments. You ensure the Airflow "
        "pipeline starts correctly with the right configuration parameters "
        "every single time."
    ),
    tools = [trigger_airflow_dag_tool],
    llm   = llm,
    verbose = True
)

monitor_workflow_agent = Agent(
    role  = "Deployment Monitor",
    goal  = (
        "Continuously watch the Airflow DAG run for task failures, "
        "upstream failures, or stalled tasks. Immediately detect and "
        "report any anomaly to the Log Analyser."
    ),
    backstory = (
        "You are a vigilant operations monitor watching HPE deployment "
        "pipelines in real time. Your job is to catch failures the moment "
        "they happen — not after an engineer notices them hours later. "
        "You never miss a failed or stalled task."
    ),
    tools = [monitor_airflow_dag_tool],
    llm   = llm,
    verbose = True
)

log_analyser_agent = Agent(
    role  = "Log Analysis Expert",
    goal  = (
        "Analyse raw Airflow task failure logs to extract structured "
        "error information — error type, exact location, diagnosis, "
        "and confidence score."
    ),
    backstory = (
        "You are an expert in HPE PCAI infrastructure logs. You have "
        "deep knowledge of MinIO, NFS, iLO, SPP, and Airflow error "
        "patterns. You extract precise, structured information from "
        "messy log text so the root cause agent can reason effectively."
    ),
    tools = [analyse_task_log_tool],
    llm   = llm,
    verbose = True
)

root_cause_agent = Agent(
    role  = "Root Cause Analyst",
    goal  = (
        "Perform deep causal reasoning on structured error reports. "
        "Classify the error type, assign severity, and determine "
        "exactly what the engineer must do to fix it."
    ),
    backstory = (
        "You are a senior HPE infrastructure engineer with 10 years of "
        "experience diagnosing deployment failures. You never guess — "
        "you reason step by step from evidence to root cause. You "
        "classify errors as transient, config, hardware, or "
        "version_mismatch with high precision."
    ),
    tools = [find_root_cause_tool],
    llm   = llm,
    verbose = True
)

alerting_agent = Agent(
    role  = "Alerting and Notification Specialist",
    goal  = (
        "Compose clear, actionable alert messages and route them "
        "to the right channels based on severity. Engineers must "
        "immediately understand what failed, why, and what to do."
    ),
    backstory = (
        "You are a communication specialist for HPE operations teams. "
        "You translate complex technical failure data into crisp, "
        "human-readable alerts. You know that a vague alert is worse "
        "than no alert — every message you send must be actionable."
    ),
    tools = [send_alert_tool],
    llm   = llm,
    verbose = True
)



# TASKS — what each agent must accomplish

def build_crew_tasks(config_json: str, sample_log_path: str) -> list:
    """Build CrewAI Task objects for a deployment run."""

    task_trigger = Task(
        description = (
            f"Trigger the Airflow deployment DAG with this config:\n"
            f"{config_json}\n"
            f"Use the trigger_airflow_dag tool and return the DAG run ID."
        ),
        expected_output = "A DAG run ID string like manual__2026-03-14T...",
        agent           = run_workflow_agent
    )

    task_monitor = Task(
        description = (
            f"Monitor the DAG run using the DAG run ID from the previous task. "
            f"Use sample_log_path: {sample_log_path} for mock mode. "
            f"Use the monitor_airflow_dag tool. "
            f"Return the TaskFailure JSON if failure detected, or NO_FAILURE."
        ),
        expected_output = "JSON string of TaskFailure or the string NO_FAILURE",
        agent           = monitor_workflow_agent,
        context         = [task_trigger]
    )

    task_analyse = Task(
        description = (
            "Take the TaskFailure JSON from the monitor task. "
            "Use the analyse_task_log tool to extract structured error info. "
            "Return the full ErrorReport JSON."
        ),
        expected_output = "JSON string of ErrorReport with error_type, diagnosis, confidence",
        agent           = log_analyser_agent,
        context         = [task_monitor]
    )

    task_rca = Task(
        description = (
            "Take the ErrorReport JSON from the log analyser task. "
            "Use the find_root_cause tool to perform root cause analysis. "
            "Return the full RootCauseReport JSON with classification and severity."
        ),
        expected_output = "JSON string of RootCauseReport with classification and severity",
        agent           = root_cause_agent,
        context         = [task_analyse]
    )

    task_alert = Task(
        description = (
            "Take the RootCauseReport JSON from the root cause task. "
            "Use the send_alert tool to compose and send the alert. "
            "Return the AlertResult JSON with the message and channels notified."
        ),
        expected_output = "JSON string of AlertResult with alert message and channels",
        agent           = alerting_agent,
        context         = [task_rca]
    )

    return [task_trigger, task_monitor, task_analyse, task_rca, task_alert]



# CREW — assemble and run

def run_crew(config_json: str, sample_log_path: str) -> str:
    """
    Assemble and run the full CrewAI pipeline.
    Returns the final alert result as a string.
    """
    tasks = build_crew_tasks(config_json, sample_log_path)

    crew = Crew(
        agents  = [
            run_workflow_agent,
            monitor_workflow_agent,
            log_analyser_agent,
            root_cause_agent,
            alerting_agent
        ],
        tasks   = tasks,
        process = Process.sequential,   # agents run in order, one at a time
        verbose = True
    )

    result = crew.kickoff()
    return str(result)
