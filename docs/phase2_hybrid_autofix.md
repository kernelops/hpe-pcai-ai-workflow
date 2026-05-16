# Phase 2: Hybrid Autofix Pipeline

The Hybrid Autofix Pipeline is the second major phase of the HPE PCAI Agent Ops platform. While Phase 1 focuses on **Detection, RCA, and Alerting**, Phase 2 introduces **Autonomous Remediation** to close the loop on infrastructure failures without human intervention.

## Architectural Overview

The Hybrid Autofix system relies on a two-attempt LangGraph execution model to handle different classes of errors. 

### Pre-requisite: DAG Analysis
Before attempting any fix, the `DagAnalysisAgent` scans the Python source code of the failing Airflow DAG. It uses a Large Language Model (LLM) combined with RAG context to determine if the failure was caused by a logical flaw in the deployment scripts (e.g., calling an invalid endpoint, using a deprecated command flag, or referencing the wrong OS release).

### Attempt 1: DAG Source Patching
If the `DagAnalysisAgent` identifies a logic flaw in the orchestration code:
1. It generates a fully corrected Python script.
2. The `DagPatchAgent` writes this script to disk as `remediation_workflow.py`.
3. The Agent triggers the new DAG via the Airflow REST API.
4. It polls Airflow for success. If the run goes green, the Autofix is complete.

### Attempt 2: SSH Infrastructure Healing
If Attempt 1 fails (or if the issue was inherently an OS/Hardware issue that cannot be fixed by changing the orchestration code):
1. **Dynamic Log Fetching**: The pipeline dynamically fetches the new error logs for the specific task that failed during Attempt 1.
2. **Re-Analysis**: The `LogAnalyserAgent` and `RootCauseAgent` process the new error to generate a fresh RCA.
3. **Fix Generation**: The `FixGeneratorAgent` creates an execution strategy. It first checks a deterministic registry for known, safe fixes (e.g., `apt-get install nfs-kernel-server`). If the issue is unknown, it falls back to the LLM to generate a custom bash fix.
4. **Fix Execution**: The `FixExecutorAgent` connects to the offending worker node via Paramiko SSH. It automatically injects the necessary credentials to handle interactive `[sudo]` password prompts.
5. **Validation**: The `ValidationAgent` runs post-execution health checks on the node and verifies that the Redis error queue is no longer receiving telemetry errors from the host.

## Entry Points
Phase 2 can be triggered through two distinct paths, representing both Active Orchestration and Passive Infrastructure Monitoring:

1. **Active Orchestrator Monitoring**: The `MonitorWorkflowAgent` actively polls the Airflow REST API. When a DAG task fails, it downloads the log and initiates the Autofix pipeline.
2. **Passive HPC Queueing**: HPC worker nodes running telemetry agents push raw error logs (e.g., syslog events, kernel panics) directly into the `hpc_error_logs` Redis Queue. The backend RQ worker consumes these logs and triggers the exact same Autofix pipeline, enabling the platform to heal nodes even when Airflow is idle.

## LangGraph Agents involved in Phase 2
- **`DagAnalysisAgent`** `[LLM-based]`: Analyzes DAG source code for broken logic and outputs a corrected Python string.
- **`DagPatchAgent`** `[Non-LLM]`: Writes the corrected source to disk and manages the Airflow REST API interactions.
- **`FixGeneratorAgent`** `[Hybrid]`: Looks up deterministic bash scripts for known issues, or uses the LLM to generate novel fixes.
- **`FixExecutorAgent`** `[Non-LLM]`: Manages the Paramiko SSH connections, PTY creation, and `sudo` handling.
- **`ValidationAgent`** `[Non-LLM]`: Ensures the system has returned to a healthy state by running verification commands and checking the Redis queue depth.
