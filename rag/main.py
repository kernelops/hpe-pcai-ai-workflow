"""
main.py
FastAPI app — entry point for the RAG pipeline.
Exposes:
  POST /analyze  → receives Airflow log, returns error location + solution
  GET  /health   → health check
  POST /ingest   → (optional) add new error+fix to knowledge base at runtime
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from log_parser import parse_airflow_log
from knowledge_base import build_knowledge_base
from rag_engine import run_rag_pipeline

load_dotenv()

# --- Global state ---
chroma_client = None
GROQ_API_KEY = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: build knowledge base and load config."""
    global chroma_client, GROQ_API_KEY

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set in environment. Check your .env file.")

    print("[Startup] Building knowledge base...")
    chroma_client = build_knowledge_base(persist_dir="./chroma_db")
    print("[Startup] Knowledge base ready.")
    print("[Startup] RAG Pipeline is live.")

    yield  # App runs here

    print("[Shutdown] Cleaning up...")


app = FastAPI(
    title="HPE PCAI RAG Pipeline",
    description="Analyzes Airflow deployment logs, identifies errors, and provides LLM-powered solutions.",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Request / Response Models ---

class AnalyzeRequest(BaseModel):
    log_text: str                  # Raw Airflow log text
    dag_id: str | None = None      # Optional override
    task_id: str | None = None     # Optional override

    class Config:
        json_schema_extra = {
            "example": {
                "log_text": "[2024-01-15 10:23:45] ERROR - task_id=configure_ilo dag_id=pcai_deploy\nTraceback (most recent call last):\n  File \"/opt/airflow/dags/tasks/ilo_config.py\", line 42, in configure_ilo\n    ilo.connect(ip='192.168.1.10', port=443)\nConnectionRefusedError: [Errno 111] Connection refused",
                "dag_id": "pcai_deploy",
                "task_id": "configure_ilo"
            }
        }


class AnalyzeResponse(BaseModel):
    error_location: str
    error_type: str
    error_message: str
    diagnosis: str
    solution: str
    prevention: str
    retrieved_sources: list[str]


class IngestRequest(BaseModel):
    error_description: str         # Description of the error
    fix_description: str           # How it was fixed
    source_label: str = "User Submitted"

    class Config:
        json_schema_extra = {
            "example": {
                "error_description": "MinIO connection timeout during configure_storage task on worker node 3",
                "fix_description": "Restarted MinIO service and updated firewall rules to allow port 9000",
                "source_label": "Field Fix #007"
            }
        }


# --- Endpoints ---

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "RAG Pipeline is running"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_log(request: AnalyzeRequest):
    """
    Main endpoint.
    Receives raw Airflow log text, returns error location + LLM solution.
    """
    if not request.log_text.strip():
        raise HTTPException(status_code=400, detail="log_text cannot be empty")

    # Step 1: Parse the log
    parsed_error = parse_airflow_log(request.log_text)

    # Allow manual override of dag_id/task_id
    if request.dag_id:
        parsed_error.dag_id = request.dag_id
    if request.task_id:
        parsed_error.task_id = request.task_id

    # Step 2: Check we actually found an error
    if parsed_error.error_message == "Unknown error" and not parsed_error.raw_traceback:
        raise HTTPException(
            status_code=422,
            detail="No error or traceback detected in the provided log. "
                   "Ensure log contains ERROR lines or a Python traceback."
        )

    # Step 3: Run RAG pipeline
    try:
        result = run_rag_pipeline(
            parsed_error=parsed_error,
            chroma_client=chroma_client,
            groq_api_key=GROQ_API_KEY,
            top_k=3,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {str(e)}")

    return AnalyzeResponse(
        error_location=result["error_location"],
        error_type=result["error_type"],
        error_message=result["error_message"],
        diagnosis=result["diagnosis"],
        solution=result["solution"],
        prevention=result["prevention"],
        retrieved_sources=result["retrieved_sources"],
    )


@app.post("/ingest")
def ingest_new_error(request: IngestRequest):
    """
    Optional endpoint to add new error+fix pairs to the knowledge base at runtime.
    Useful as your team encounters and fixes new errors.
    """
    from knowledge_base import ERRORS_COLLECTION, get_embedding_function
    import uuid

    ef = get_embedding_function()
    col = chroma_client.get_collection(name=ERRORS_COLLECTION, embedding_function=ef)

    new_id = f"err_{uuid.uuid4().hex[:8]}"
    combined_text = (
        f"Error: {request.error_description}\n"
        f"Fix Applied: {request.fix_description}"
    )

    col.add(
        ids=[new_id],
        documents=[combined_text],
        metadatas=[{"source": request.source_label}],
    )

    return {
        "status": "ingested",
        "id": new_id,
        "message": f"New error+fix added to knowledge base with id {new_id}"
    }


# --- Run directly ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)