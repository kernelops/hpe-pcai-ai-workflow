# HPE PCAI Agent Ops and Deployment Platform

An integrated development stack for running an Airflow-driven infrastructure deployment workflow with:

- a React frontend for worker-node management, deployment control, live logs, and Agent Ops cards
- a FastAPI backend that triggers and monitors Airflow runs
- a LangGraph-based agent pipeline for failure analysis
- a ChromaDB-backed RAG service for historical error retrieval and fix suggestions

This `dev` branch is the integration branch for frontend, Airflow, backend, agents, and RAG.

## Architecture

The stack is split into five runtime services:

1. Airflow
   Runs the `deployment_workflow` DAG and produces task logs.
2. RAG Service
   Retrieves similar HPE docs and past incident patterns from ChromaDB.
3. Agent API
   Runs the agent pipeline and exposes failure-analysis endpoints.
4. Backend API
   Triggers DAG runs, streams live logs, validates worker nodes, and proxies Agent Ops requests.
5. Frontend
   Provides the UI for nodes, SSH validation, deployments, log insights, and Agent Ops.

High-level flow:

1. Add worker nodes in the frontend.
2. Validate SSH reachability.
3. Start the Airflow deployment DAG from the UI.
4. Backend streams combined logs from Airflow.
5. On failure, backend sends the failed task log block to Agent Ops.
6. Agent pipeline calls RAG, performs root-cause reasoning, and returns remediation guidance.

## Repository Layout

```text
hpe-pcai-ai-workflow/
├── agents/                  # LangGraph agents
├── airflow/                 # Local Airflow stack and DAGs
├── api/                     # Agent Ops API
├── backend/                 # Deployment/backend API used by the frontend
├── common/                  # Shared config and models
├── frontend/                # React + Vite UI
├── rag/                     # RAG API, knowledge base, retrieval pipeline
├── chroma_db/               # Local Chroma persistence
└── README.md
```

## Prerequisites

- Linux or macOS development environment
- Python 3.10+ with a virtual environment
- Node.js 18+ and npm
- Docker Engine with Docker Compose
- At least one reachable Linux VM or host with SSH enabled

Optional:

- `GROQ_API_KEY` for better LLM-backed RAG synthesis
- external Slack/email credentials if you extend alert delivery

## One-Time Setup

### 1. Clone and switch to the integration branch

```bash
git clone <your-repo-url>
cd hpe-pcai-ai-workflow
git checkout dev
export REPO_ROOT="$(pwd)"
```

### 2. Create and activate a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
pip install -r rag/requirements.txt
pip install httpx
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd "$REPO_ROOT"
```

## Run the Full Stack

Start the services in the order below. Keep each terminal open.

### Terminal 1: Airflow

```bash
cd "$REPO_ROOT/airflow"
echo "AIRFLOW_UID=$(id -u)" > .env
mkdir -p logs config plugins
docker compose up -d
docker compose exec airflow-webserver airflow dags unpause deployment_workflow
docker compose exec airflow-webserver airflow dags list | grep deployment_workflow
```

Expected result:

- Airflow webserver becomes available on `http://127.0.0.1:8080`
- `deployment_workflow` appears with `False` in the paused column

Airflow UI credentials:

- Username: `airflow`
- Password: `airflow`

### Terminal 2: RAG Service

`RAG_FORCE_LOCAL_EMBEDDINGS=1` keeps local development working even without remote embedding downloads.

```bash
cd "$REPO_ROOT"
source .venv/bin/activate
RAG_FORCE_LOCAL_EMBEDDINGS=1 python -m uvicorn rag.main:app --host 0.0.0.0 --port 8002
```

Expected health endpoint:

```bash
curl http://127.0.0.1:8002/health
```

### Terminal 3: Agent API

```bash
cd "$REPO_ROOT"
source .venv/bin/activate
RAG_API_URL=http://127.0.0.1:8002 python -m uvicorn api.main:app --host 0.0.0.0 --port 8001
```

Expected health endpoint:

```bash
curl http://127.0.0.1:8001/health
```

### Terminal 4: Backend API

```bash
cd "$REPO_ROOT"
source .venv/bin/activate
AIRFLOW_BASE_URL=http://127.0.0.1:8080 \
AIRFLOW_DAG_ID=deployment_workflow \
AIRFLOW_USERNAME=airflow \
AIRFLOW_PASSWORD=airflow \
AGENT_OPS_API_URL=http://127.0.0.1:8001/api/agents/analyze-failure \
AIRFLOW_LOGS_PATH="$REPO_ROOT/airflow/logs" \
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Expected health endpoint:

```bash
curl http://127.0.0.1:8000/
```

### Terminal 5: Frontend

```bash
cd "$REPO_ROOT/frontend"
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Frontend URL:

- `http://127.0.0.1:5173`

## Quick Verification

Run these from a separate terminal once all services are up:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/
curl -u airflow:airflow http://127.0.0.1:8080/api/v1/dags/deployment_workflow/details
```

## Using the UI

### 1. Add worker nodes

Open the frontend and go to `Worker Nodes`.

For each target VM:

- enter the node IP address
- enter the SSH username
- enter the SSH password
- save the node

### 2. Validate SSH

Go to `SSH Validation` and click `Run SSH Health Check`.

Recommended status before deployment:

- `Ping`: `PASS`
- `SSH 22`: `OPEN`

Notes:

- `REFUSED` means the machine is reachable but nothing is listening on port 22
- `TIMEOUT` usually means a routing, firewall, or network path issue

### 3. Start a deployment

Go to `Deployment` and click `Start Infrastructure Deployment`.

What happens next:

- backend triggers the Airflow DAG
- frontend polls live logs from the backend
- `Workflow Monitor` displays merged task output
- on failure, Agent Ops is triggered automatically

### 4. Review failure analysis

On a failed run, open `Agent Ops` to inspect:

- workflow agent context
- monitor agent context
- log analysis output
- root cause classification and severity
- alerting output and remediation guidance

## RAG Behavior in This Branch

RAG no longer queries Chroma using only a generic Airflow exception.

The current query combines:

- Airflow `task_id`
- task-based domain hints such as `minio`, `nfs`, or `postcheck`
- parsed `error_type`
- parsed `error_message`
- raw log evidence such as command text and keywords like `curl`, `exportfs`, `broken_option`, `sudo`, `connection refused`, or `timed out`

This makes retrieval more specific to the failing task and better aligned with the knowledge base contents.

## Troubleshooting

### DAG does not start

Check that Airflow is running and the DAG is unpaused:

```bash
cd "$REPO_ROOT/airflow"
docker compose ps
docker compose exec airflow-webserver airflow dags list | grep deployment_workflow
```

### Frontend is blank or shows zero nodes

The backend currently stores worker nodes in memory only. If the backend restarts, node state is lost and must be re-added from the UI.

Check current backend state:

```bash
curl http://127.0.0.1:8000/nodes
```

### SSH shows `REFUSED`

The host is reachable, but SSH is not listening on port 22.

Check on the target VM:

```bash
sudo systemctl status ssh
sudo systemctl start ssh
sudo systemctl enable ssh
ss -tuln | grep :22
```

### No live logs appear

Check backend log-path configuration and Airflow task logs:

```bash
cd "$REPO_ROOT/airflow"
find logs -maxdepth 6 -type f | tail
docker compose logs --tail=200 airflow-scheduler
docker compose logs --tail=200 airflow-worker
```

### Agent Ops shows analysis but `Rag Solution` is blank

Possible causes:

- the RAG service is not running
- the agent API is not pointing to the correct `RAG_API_URL`
- the failure matched generic evidence with no strong knowledge-base hit

Check services:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8001/health
```

### RAG returns `500 Internal Server Error`

Restart the RAG service using forced local embeddings:

```bash
cd "$REPO_ROOT"
source .venv/bin/activate
RAG_FORCE_LOCAL_EMBEDDINGS=1 python -m uvicorn rag.main:app --host 0.0.0.0 --port 8002
```

## Development Notes

- This branch is intended for integration and local validation before merging into `main`
- Airflow runs locally through Docker Compose and is not production hardened
- Worker node persistence is not yet implemented
- Local RAG fallback mode is supported for offline development

## Shutdown

Stop the `uvicorn` and frontend processes with `Ctrl+C`.

To stop Airflow:

```bash
cd "$REPO_ROOT/airflow"
docker compose down
```
