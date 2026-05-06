"""
main.py
FastAPI app — entry point for the RAG pipeline.
Exposes:
  POST /analyze  → receives Airflow log, returns error location + KB-matched solutions
  GET  /health   → health check
  POST /ingest   → add new error+fix to knowledge base at runtime
"""

import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

try:
    from .log_parser import parse_airflow_log
    from .knowledge_base import build_knowledge_base, ERRORS_COLLECTION, get_embedding_function
    from .rag_engine import run_rag_pipeline
except ImportError:
    from log_parser import parse_airflow_log
    from knowledge_base import build_knowledge_base, ERRORS_COLLECTION, get_embedding_function
    from rag_engine import run_rag_pipeline

load_dotenv()

# --- Global state ---
chroma_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: build knowledge base."""
    global chroma_client

    print("[Startup] Building knowledge base...")
    chroma_client = build_knowledge_base(persist_dir="./chroma_db")
    print("[Startup] Knowledge base ready.")
    print("[Startup] RAG Pipeline is live.")

    yield

    print("[Shutdown] Cleaning up...")


app = FastAPI(
    title="HPE PCAI RAG Pipeline",
    description="Analyzes Airflow deployment logs, identifies errors, and returns KB-matched solutions.",
    version="2.0.0",
    lifespan=lifespan,
)


# --- Request / Response Models ---

class AnalyzeRequest(BaseModel):
    log_text: str
    dag_id: str | None = None
    task_id: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "log_text": "[2026-05-05T08:38:23.680+0000] {taskinstance.py:2905} ERROR - Task failed with exception\nTraceback (most recent call last):\n...\nairflow.exceptions.AirflowException: SSH command timed out",
                "dag_id": "deployment_workflow",
                "task_id": "simulate_nfs_configuration_error"
            }
        }


class KBMatch(BaseModel):
    matched_line: str           # The log line that triggered this match
    similarity: float           # Similarity score (0-1)
    kb_document: str            # The KB error_line that was matched
    diagnosis: str
    solution: str
    prevention: str
    error_type: str
    severity: str
    source: str
    retrieved_sources: str      # URLs / references from KB entry


class AnalyzeResponse(BaseModel):
    error_location: str
    error_type: str
    error_message: str
    matches: list[KBMatch]      # All KB entries that survived threshold + dedup
    retrieved_sources: list[str]


class IngestRequest(BaseModel):
    error_line: str             # The exact error string to embed and match against
    diagnosis: str
    solution: str
    prevention: str
    error_type: str = "Unknown"
    severity: str = "Medium"
    source_label: str = "User Submitted"
    retrieved_sources: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "error_line": "MinIO connection timeout during configure_storage task",
                "diagnosis": "MinIO server is unreachable on port 9000",
                "solution": "Restart MinIO service and verify firewall rules allow port 9000",
                "prevention": "Add a MinIO health check before running configure_storage",
                "error_type": "Connection error",
                "severity": "Medium",
                "source_label": "Field Fix #007",
                "retrieved_sources": ""
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
    Receives raw Airflow log text, returns error location + KB-matched solutions.
    No LLM involved — diagnosis/solution/prevention come directly from the knowledge base.
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
                   "Ensure the log contains ERROR lines or a Python traceback."
        )

    # Step 3: Run RAG pipeline
    try:
        result = run_rag_pipeline(
            parsed_error=parsed_error,
            chroma_client=chroma_client,
            top_k=1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {str(e)}")

    return AnalyzeResponse(
        error_location=result["error_location"],
        error_type=result["error_type"],
        error_message=result["error_message"],
        matches=result["matches"],
        retrieved_sources=result["retrieved_sources"],
    )


@app.post("/ingest")
def ingest_new_error(request: IngestRequest):
    """
    Add a new error+fix pair to the knowledge base at runtime.
    Only the error_line is embedded. All other fields go into metadata.
    """
    ef = get_embedding_function()
    col = chroma_client.get_collection(name=ERRORS_COLLECTION, embedding_function=ef)

    new_id = f"err_{uuid.uuid4().hex[:8]}"

    col.add(
        ids=[new_id],
        documents=[request.error_line],
        metadatas=[{
            "source": request.source_label,
            "error_type": request.error_type,
            "severity": request.severity,
            "diagnosis": request.diagnosis,
            "solution": request.solution,
            "prevention": request.prevention,
            "retrieved_sources": request.retrieved_sources,
        }],
    )

    return {
        "status": "ingested",
        "id": new_id,
        "message": f"New error+fix added to knowledge base with id {new_id}"
    }


# --- Run directly ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("rag.main:app", host="0.0.0.0", port=8002, reload=True)
