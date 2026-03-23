@echo off
echo Starting AI Infrastructure Deployment Platform...
echo.

echo [1/4] Starting Backend Server...
start "Backend Server" cmd /k "cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

echo [2/4] Starting Airflow Webserver...
start "Airflow Webserver" cmd /k "airflow webserver -p 8080"

echo [3/4] Starting Airflow Scheduler...
start "Airflow Scheduler" cmd /k "airflow scheduler"

echo [4/4] Starting Frontend...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo All services starting...
echo.
echo Access URLs:
echo - Frontend: http://localhost:5173
echo - Backend: http://localhost:8000
echo - Airflow: http://localhost:8080
echo.
echo Wait 30 seconds, then run: python setup_airflow_connections.py
echo.
pause
