@echo off
echo ===================================================
echo   Starting HPE PCAI — Windows Full Stack Launcher
echo ===================================================
echo.

:: Check for virtual environment
if not exist .venv (
    echo [ERROR] Virtual environment .venv not found!
    echo Please run: py -3.11 -m venv .venv
    echo And: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: Start Airflow and Redis via Docker
echo [1/6] Starting Airflow and Redis (Docker Compose)...
cd airflow
docker compose up -d
cd ..
echo.

:: Start RAG Service
echo [2/6] Starting RAG Service (Port 8002)...
set RAG_FORCE_LOCAL_EMBEDDINGS=1
start "RAG Service" cmd /k ".venv\Scripts\python -m uvicorn rag.main:app --host 0.0.0.0 --port 8002"

:: Start Agent API
echo [3/6] Starting Agent API (Port 8001)...
set RAG_API_URL=http://127.0.0.1:8002
start "Agent API" cmd /k ".venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8001"

:: Start Backend API
echo [4/6] Starting Backend API (Port 8000)...
set AIRFLOW_BASE_URL=http://127.0.0.1:8080
set AIRFLOW_DAG_ID=deployment_workflow
set AIRFLOW_USERNAME=airflow
set AIRFLOW_PASSWORD=airflow
set AGENT_OPS_API_URL=http://127.0.0.1:8001/api/agents/analyze-failure
set AGENT_OPS_BASE_URL=http://127.0.0.1:8001
set AIRFLOW_LOGS_PATH=airflow/logs
start "Backend API" cmd /k ".venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

:: Start RQ Worker
echo [5/6] Starting RQ Worker...
start "RQ Worker" cmd /k ".venv\Scripts\rq worker hpc_error_logs --url redis://localhost:6379/0"

:: Start Frontend
echo [6/6] Starting React Frontend (Port 5173)...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo All services starting in separate windows.
echo Access URLs:
echo - Frontend: http://localhost:5173
echo - Backend: http://localhost:8000
echo - Agent API: http://localhost:8001
echo - RAG Service: http://localhost:8002
echo - Airflow: http://localhost:8080
echo.
echo Wait 30 seconds for Airflow to warm up, then run:
echo   .venv\Scripts\python setup_airflow_connections.py
echo.
pause
