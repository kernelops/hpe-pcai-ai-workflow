# AI Infrastructure Deployment Platform


Web dashboard for Airflow-driven infrastructure deployments, live log monitoring, LLM-based log analysis, and Agent Ops incident response.

---

Overview

This project provides a web-based operations dashboard for:

- managing worker nodes
- validating SSH connectivity
- triggering the Airflow DAG `deployment_workflow`
- streaming combined deployment logs in real time
- generating structured LLM summaries from parsed logs
- auto-triggering Agent Ops analysis when a run contains failure signals
- displaying per-agent outputs in a dedicated `Agent Ops` panel

End-To-End Flow

Deployment

1. Add worker nodes from the `Worker Nodes` tab.
2. Start deployment from the `Deployment` tab.
3. The backend triggers the Airflow DAG `deployment_workflow`.
4. The frontend polls run state and live logs.
5. `Workflow Monitor` displays merged task logs in real time.

Log Insights

1. Combined Airflow logs are collected by the backend.
2. `backend/log_parser.py` splits logs into task sections.
3. Failed task evidence is extracted from those sections.
4. `Generate LLM Summary` sends structured task-wise context to the LLM.

Agent Ops

1. A deployment run reaches a failed state or contains strong failure signals in its logs.
2. The frontend automatically calls `POST /agent-ops/analyze` on the backend.
3. The backend extracts the failed task and its raw failed-task log block.
4. The backend forwards that payload to the external Agent Ops API.
5. The Agent Ops response populates:
   - Workflow Agent
   - Monitor Agent
   - Log Analysis Agent
   - Root Cause Agent
   - Alerting Agent
   - Combined Summary

Repository Layout

```text
infra-ai-deployer/
|-- airflow/
|   `-- dags/
|       `-- deployment_workflow.py
|-- backend/
|   |-- direct_log_reader.py
|   |-- log_parser.py
|   |-- main.py
|   `-- static/
|-- frontend/
|   |-- package.json
|   `-- src/
|       |-- App.jsx
|       |-- styles.css
|       `-- assets/
`-- README.md
```

Key Files

[deployment_workflow.py](C:\Users\Hp\Desktop\infra-ai-deployer\airflow\dags\deployment_workflow.py)

- Airflow DAG used by the app
- currently configured as a failure-simulation workflow

[main.py](C:\Users\Hp\Desktop\infra-ai-deployer\backend\main.py)

- FastAPI backend
- Airflow trigger and log endpoints
- LLM summary endpoint
- Agent Ops proxy endpoint

[log_parser.py](C:\Users\Hp\Desktop\infra-ai-deployer\backend\log_parser.py)

- task-wise log parsing
- failed task extraction for LLM and Agent Ops

[App.jsx](C:\Users\Hp\Desktop\infra-ai-deployer\frontend\src\App.jsx)

- React UI
- deployment polling
- Log Insights
- Agent Ops panel

Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- running Airflow instance with API access
- optional LLM provider credentials
- optional separate Agent Ops API

Backend Setup

```bash
cd backend

# Activate your virtual environment if you use one
# Windows
venv\Scripts\activate

pip install fastapi uvicorn httpx

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend URLs:

- app: `http://localhost:8000`
- docs: `http://localhost:8000/docs`

Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

If PowerShell blocks `npm`, use:

```bash
npm.cmd run dev
```

Backend Environment Variables

Set these before starting the backend:

```bash
AIRFLOW_BASE_URL=http://host.docker.internal:8080
AIRFLOW_DAG_ID=deployment_workflow
AIRFLOW_USERNAME=airflow
AIRFLOW_PASSWORD=airflow

LLM_API_KEY=your_key
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1

AGENT_OPS_API_URL=http://127.0.0.1:8001/api/agents/analyze-failure
```

Agent Ops Service

The dashboard expects a separate Agent Ops API that supports:

- `POST /api/agents/analyze-failure`

Expected request shape:

```json
{
  "dag_id": "deployment_workflow",
  "dag_run_id": "manual__2026-03-23T10:00:00",
  "failed_task": "simulate_nfs_configuration_error/map_index=0",
  "task_state": "failed",
  "log_text": "raw failed task log block",
  "timestamp": "2026-03-23T16:30:00"
}
```

Routing flow:

- frontend -> `POST /agent-ops/analyze` on this backend
- backend -> external Agent Ops API

Airflow DAG Notes

The current DAG is a failure-simulation workflow used for testing log analysis:

- `simulate_os_validation_error`
- `simulate_nfs_configuration_error`
- `simulate_minio_service_error`
- `simulate_postcheck_error`

These tasks intentionally generate realistic failure categories such as:

- OS baseline mismatch
- NFS export configuration error
- missing service or unit file
- connection refused or failed health check

Current Backend API

Node Management

- `GET /nodes`
- `POST /nodes`
- `DELETE /nodes/{node_id}`
- `POST /nodes/refresh_status`
- `GET /nodes/{node_id}/diagnostics`

Deployment

- `POST /deployments/start`
- `GET /deployments/{run_id}/logs/{task_id}`
- `GET /deployments/{run_id}/logs/{task_id}/direct`
- `GET /deployments/{run_id}/live-logs`

Analysis

- `POST /logs/summarize-llm`
- `POST /agent-ops/analyze`

Agent Ops Triggering Notes

Agent Ops analysis is auto-triggered when:

- the run status becomes `Failed`
- or combined logs contain strong failure signals

Current limitation:

- the backend currently sends one failed task log block to the agent API
- if multiple tasks fail in parallel, the first failed task section found in the merged log stream is analyzed

Troubleshooting

If backend starts but LLM summary fails, check:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- connectivity to the LLM provider

If Agent Ops stays empty, check:

- the Agent Ops API is running
- `AGENT_OPS_API_URL` points to the correct service
- the run logs contain a detectable failed task section

If no logs appear, check:

- Airflow is reachable from the backend
- the DAG run exists
- `direct_log_reader.py` can access task log directories

Future Improvements

- analyze all failed tasks instead of only the first detected failure
- tighten failed-task extraction when tasks run in parallel
- improve structured agent output rendering in the dashboard
- align LLM summary and Agent Ops task selection logic
