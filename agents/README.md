# Agents Folder

This folder contains the agent layer for the HPE PCAI workflow. The code here is responsible for triggering an Airflow deployment, monitoring execution, analysing failures, reasoning about root cause, and sending alerts.

The folder supports two execution styles that reuse the same underlying agent logic:

1. **LangGraph pipeline** in [workflow_graph.py](workflow_graph.py) - the main orchestrated path used by [main.py](../main.py)
2. **CrewAI wrapper** in [crew_agents.py](crew_agents.py) - an alternate agent orchestration layer that wraps the same logic as CrewAI tools and tasks

## High-level flow

The normal end-to-end flow is:

`DeploymentConfig` -> `RunWorkflowAgent` -> `dag_run_id` -> `MonitorWorkflowAgent` -> `TaskFailure` -> `LogAnalyserAgent` -> `ErrorReport` -> `RootCauseAgent` -> `RootCauseReport` -> `AlertingAgent` -> `AlertResult`

If no failure is detected, the pipeline stops after monitoring and returns a success state. If a failure is found, the pipeline continues through analysis, root cause reasoning, and alerting.

## Folder Map

- [run_workflow_agent.py](run_workflow_agent.py): triggers the Airflow DAG and returns a DAG run ID
- [monitor_workflow_agent.py](monitor_workflow_agent.py): watches the DAG run, detects failures or stalls, and returns task failure details
- [log_analyser_agent.py](log_analyser_agent.py): turns raw task logs into a structured error report using Groq and optional RAG context
- [root_cause_agent.py](root_cause_agent.py): reasons over the structured error report and produces a root cause classification
- [alerting_agent.py](alerting_agent.py): generates a human-readable alert and sends it to notification channels
- [workflow_graph.py](workflow_graph.py): connects the agents into a LangGraph state machine
- [crew_agents.py](crew_agents.py): exposes the same capabilities as CrewAI agents, tools, and sequential tasks

## How The Agents Are Connected

### 1. Trigger stage

`RunWorkflowAgent` starts the pipeline by calling the Airflow REST API.

What it does:

- checks Airflow health
- builds the DAG trigger payload from `DeploymentConfig`
- starts the DAG run
- returns `dag_run_id`

Data passed forward:

- `DeploymentConfig`
- `dag_run_id`

### 2. Monitor stage

`MonitorWorkflowAgent` polls Airflow for task status.

What it does:

- fetches task instances for the DAG run
- waits for terminal task states
- detects failures or tasks that stall longer than the configured timeout
- fetches the failing task log when needed

Data passed forward:

- `dag_run_id`
- `TaskFailure` when something fails
- `None` when the run succeeds

### 3. Log analysis stage

`LogAnalyserAgent` converts raw log text into a structured failure summary.

What it does:

- optionally calls the RAG service for supporting context
- sends the raw log and context to Groq
- extracts a strict JSON error report

Data passed forward:

- `TaskFailure`
- `ErrorReport`

### 4. Root cause stage

`RootCauseAgent` reasons over the structured error report.

What it does:

- classifies the failure as `transient`, `config`, `hardware`, or `version_mismatch`
- assigns severity as `critical`, `high`, or `low`
- recommends one concrete engineer action

Data passed forward:

- `ErrorReport`
- `RootCauseReport`

### 5. Alerting stage

`AlertingAgent` produces the final operational message.

What it does:

- writes a short, actionable alert message with Groq
- sends the alert to Slack when severity is `high` or `critical`
- always prints the alert to the console

Data passed forward:

- `RootCauseReport`
- `AlertResult`

## LangGraph Orchestration

[workflow_graph.py](workflow_graph.py) is the main control layer for the agent pipeline.

It defines a shared `PipelineState` object that carries all data across nodes:

- `deployment_config`: deployment input used to trigger Airflow
- `sample_log_path`: mock mode log path; empty string means real Airflow mode
- `dag_run_id`: Airflow run identifier
- `task_failure`: failure details from monitoring
- `error_report`: structured log analysis output
- `rca_report`: root cause analysis output
- `alert_result`: final alert output
- `failure_detected`: boolean routing flag
- `pipeline_status`: running, success, failed, or alerted

### Routing logic

The graph runs in this order:

1. `run_workflow`
2. `monitor`
3. if no failure, `success` and stop
4. if failure, `log_analyser`
5. `root_cause`
6. if severity is `low`, `log_only` and stop
7. if severity is `high` or `critical`, `alert` and stop

This means the graph behaves like a decision tree:

- success path: trigger -> monitor -> end
- failure path: trigger -> monitor -> log analysis -> root cause -> alert/log only -> end

## Mock Mode vs Real Mode

The agents support two data sources:

### Mock mode

When `sample_log_path` is set:

- `RunWorkflowAgent.trigger_dag_mock()` returns a synthetic DAG run ID
- `MonitorWorkflowAgent.monitor_mock()` loads a sample failure log from disk
- the rest of the pipeline behaves the same

This is useful for local testing and demos without needing a live Airflow system.

### Real mode

When `sample_log_path` is empty:

- `RunWorkflowAgent.trigger_dag()` calls the Airflow REST API
- `MonitorWorkflowAgent.monitor()` polls live task instances
- `get_task_log()` fetches the real task log from Airflow
- log analysis, root cause reasoning, and alerting continue from the real failure data

## Shared Data Models

The agent chain uses the shared Pydantic models defined in [common/models.py](../common/models.py):

- `DeploymentConfig`: input configuration for the deployment run
- `TaskFailure`: monitoring output when a task fails or stalls
- `ErrorReport`: structured interpretation of the raw log
- `RootCauseReport`: root cause, classification, severity, and action
- `AlertResult`: final notification payload

These models are important because each agent passes typed data to the next stage instead of unstructured text.

## CrewAI Wrapper

[crew_agents.py](crew_agents.py) reuses the same underlying classes, but exposes them in CrewAI format.

It does three things:

- wraps each agent method as a CrewAI tool
- defines CrewAI agent personas with roles, goals, and backstories
- assembles the pipeline as sequential CrewAI tasks

The CrewAI flow mirrors the LangGraph flow:

1. trigger DAG
2. monitor DAG
3. analyse log
4. find root cause
5. send alert

The difference is orchestration style:

- LangGraph uses explicit state transitions and conditional routing
- CrewAI uses task context chaining and sequential task execution

## Where This Folder Is Used

- [main.py](../main.py) imports `run_graph()` and runs the LangGraph pipeline for local testing
- [api/main.py](../api/main.py) instantiates the same agent classes directly to serve the API endpoint

So the agents folder is the shared execution core for both the command-line test flow and the API flow.

## Summary

This folder is the decision-making layer of the workflow. The agents do not just call services independently; they pass structured data from one stage to the next so the system can move from deployment trigger to monitoring, then to analysis, root cause reasoning, and finally alerting.
