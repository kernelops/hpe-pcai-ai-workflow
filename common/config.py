# common/config.py
import os
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
GROQ_MODEL       = "llama-3.3-70b-versatile"

AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://localhost:8080")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME", "admin")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "admin")
AIRFLOW_DAG_ID   = os.getenv("AIRFLOW_DAG_ID", "pcai_deployment")

SLACK_WEBHOOK    = os.getenv("SLACK_WEBHOOK_URL", "")
RAG_API_URL      = os.getenv("RAG_API_URL", "")   # empty until RAG is ready

POLL_INTERVAL_SEC   = 10    # how often Monitor Agent polls Airflow
TASK_TIMEOUT_SEC    = 300   # task stall threshold (5 mins)
