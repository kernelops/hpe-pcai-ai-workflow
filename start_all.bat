@echo off
echo Starting AI Infrastructure Deployment Platform...
echo.

echo [1/5] Starting Backend Server...
start "Backend Server" cmd /k "call .venv\Scripts\activate && cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

echo [2/5] Starting Agent Ops API...
start "Agent Ops API" cmd /k "call .venv\Scripts\activate && uvicorn api.main:app --reload --host 0.0.0.0 --port 8001"

echo [3/5] Starting RAG Pipeline...
start "RAG Pipeline" cmd /k "call .venv\Scripts\activate && cd rag && uvicorn main:app --reload --host 0.0.0.0 --port 8002"

echo [4/5] Starting Airflow (Docker)...
start "Airflow Env" cmd /k "cd airflow && docker-compose up -d && echo Airflow is starting in the background. Close this terminal if you wish. && pause"

echo [5/5] Starting Frontend...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo All services starting...
echo.
echo Access URLs:
echo - Frontend: http://localhost:5173
echo - Backend API: http://localhost:8000
echo - Agent Ops API: http://localhost:8001
echo - RAG Pipeline: http://localhost:8002
echo - Airflow: http://localhost:8080
echo.
echo Wait 30 seconds, then run: python setup_airflow_connections.py
echo.
pause
