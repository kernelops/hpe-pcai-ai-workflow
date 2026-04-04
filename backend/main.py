import os
import socket
from typing import List, Literal, Optional
import uuid
import glob
from pathlib import Path
import re

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime

try:
    from .direct_log_reader import log_reader
    from .log_parser import build_agent_failure_payloads, build_llm_log_context
except ImportError:
    from direct_log_reader import log_reader
    from log_parser import build_agent_failure_payloads, build_llm_log_context


AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://host.docker.internal:8080")
AIRFLOW_DAG_ID = os.getenv("AIRFLOW_DAG_ID", "deployment_workflow")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME", "airflow")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "airflow")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
AGENT_OPS_API_URL = os.getenv("AGENT_OPS_API_URL", "http://127.0.0.1:8001/api/agents/analyze-failure")


class WorkerNodeBase(BaseModel):
    ip: str
    username: str
    password: str


class WorkerNode(WorkerNodeBase):
    status: Literal["unknown", "reachable", "unreachable"] = "unknown"
    last_checked: Optional[datetime] = None


class DeploymentStartResponse(BaseModel):
    run_id: str
    state: Optional[Literal["queued", "running", "success", "failed", "up_for_retry", "upstream_failed"]] = None
    message: str


class DeploymentLogResponse(BaseModel):
    run_id: str
    task_id: str
    state: Optional[str]
    log: str


class DeploymentLiveLogResponse(BaseModel):
    run_id: str
    state: Optional[str]
    log: str
    task_streams: int


class LogSummaryRequest(BaseModel):
    run_id: Optional[str] = None
    status: Optional[str] = None
    logs: str


class LogSummaryResponse(BaseModel):
    summary: str
    executed_steps: List[str]
    security_suggestions: List[str]
    root_causes: List[str] = []
    recommended_actions: List[str] = []
    confidence: str


class AgentOpsAnalyzeRequest(BaseModel):
    run_id: str
    status: str
    logs: str


app = FastAPI(title="Infra AI Deployer Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


worker_nodes: List[WorkerNode] = []


def _check_node_connectivity(node: WorkerNode) -> tuple[str, datetime]:
    """
    Flexible connectivity check with multiple methods.
    """
    status: Literal["reachable", "unreachable"] = "unreachable"
    now = datetime.utcnow()
    
    print(f"Checking connectivity to {node.ip}...")
    
    # Method 1: Try ping first (less strict)
    ping_success = False
    try:
        import subprocess
        import platform
        
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", "2000", node.ip]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", node.ip]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ping_success = True
            print(f"✓ Ping successful to {node.ip}")
        else:
            print(f"⚠ Ping failed to {node.ip}: {result.stderr[:100]}")
    except Exception as e:
        print(f"⚠ Ping check failed: {e}")
    
    # Method 2: Try SSH connection to port 22
    ssh_success = False
    try:
        print(f"Attempting SSH connection to {node.ip}:22...")
        with socket.create_connection((node.ip, 22), timeout=5):
            ssh_success = True
            print(f"✓ SSH connection successful to {node.ip}:22")
    except socket.timeout:
        print(f"⚠ SSH timeout to {node.ip}:22")
    except ConnectionRefusedError:
        print(f"⚠ SSH connection refused by {node.ip}:22")
    except OSError as e:
        print(f"⚠ SSH network error to {node.ip}: {e}")
    except Exception as e:
        print(f"⚠ SSH unexpected error to {node.ip}: {e}")
    
    # Method 3: Try alternative SSH ports
    alt_port_success = False
    if not ssh_success:
        common_ports = [2222, 2022, 2020]
        for port in common_ports:
            try:
                print(f"Trying alternative port {node.ip}:{port}...")
                with socket.create_connection((node.ip, port), timeout=3):
                    alt_port_success = True
                    print(f"✓ Found SSH on alternative port {port}")
                    break
            except:
                continue
    
    # Determine final status - be more lenient
    if ping_success or ssh_success or alt_port_success:
        status = "reachable"
        print(f"✓ Node {node.ip} marked as REACHABLE (ping: {ping_success}, ssh: {ssh_success}, alt_port: {alt_port_success})")
    else:
        status = "unreachable"
        print(f"⚠ Node {node.ip} marked as UNREACHABLE (all methods failed)")
    
    return status, now


@app.get("/")
def home():
    return {"message": "Infra AI Deployer Backend Running"}


@app.get("/dashboard")
def dashboard_entry():
    return {"url": "/static/index.html"}


@app.post("/nodes", response_model=WorkerNode)
def add_node(node: WorkerNodeBase):
    """
    Add a new worker node with connectivity check.
    """
    try:
        # Validate IP address format
        socket.inet_aton(node.ip)
    except socket.error:
        raise HTTPException(status_code=400, detail="Invalid IP address format")
    
    # Check if node already exists
    existing_node = next((n for n in worker_nodes if n.ip == node.ip and n.username == node.username), None)
    if existing_node:
        raise HTTPException(status_code=409, detail="Node with this IP and username already exists")
    
    print(f"Adding node: {node.ip} ({node.username})")
    
    # Check connectivity immediately when adding a node
    status, checked_at = _check_node_connectivity(node)
    
    # Create node with status
    node_with_status = WorkerNode(**node.dict(), status=status, last_checked=checked_at)
    worker_nodes.append(node_with_status)
    
    print(f"Node added successfully: {node.ip} - Status: {status}")
    return node_with_status


@app.get("/nodes", response_model=List[WorkerNode])
def list_nodes():
    return worker_nodes


@app.get("/nodes/{node_id}/diagnostics")
def get_node_diagnostics(node_id: int):
    """
    Get detailed diagnostics for a specific worker node.
    """
    if 0 <= node_id < len(worker_nodes):
        node = worker_nodes[node_id]
        diagnostics = {
            "node": {
                "ip": node.ip,
                "username": node.username,
                "status": node.status,
                "last_checked": node.last_checked.isoformat() if node.last_checked else None
            },
            "tests": {}
        }
        
        # Test 1: Ping test
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", "1000", node.ip]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", node.ip]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            diagnostics["tests"]["ping"] = {
                "success": result.returncode == 0,
                "output": result.stdout[:200] + "..." if len(result.stdout) > 200 else result.stdout,
                "error": result.stderr[:200] + "..." if len(result.stderr) > 200 else result.stderr
            }
        except Exception as e:
            diagnostics["tests"]["ping"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test 2: Port scan for common SSH ports
        ssh_ports = [22, 2222, 2022, 2020]
        port_results = {}
        
        for port in ssh_ports:
            try:
                with socket.create_connection((node.ip, port), timeout=2):
                    port_results[str(port)] = "open"
            except socket.timeout:
                port_results[str(port)] = "timeout"
            except ConnectionRefusedError:
                port_results[str(port)] = "refused"
            except OSError as e:
                port_results[str(port)] = f"error: {str(e)[:50]}"
            except Exception as e:
                port_results[str(port)] = f"unknown: {str(e)[:50]}"
        
        diagnostics["tests"]["port_scan"] = port_results
        
        # Test 3: DNS resolution
        try:
            hostname = socket.gethostbyaddr(node.ip)
            diagnostics["tests"]["dns"] = {
                "success": True,
                "hostname": hostname[0],
                "aliases": hostname[1]
            }
        except Exception as e:
            diagnostics["tests"]["dns"] = {
                "success": False,
                "error": str(e)
            }
        
        return diagnostics
    else:
        raise HTTPException(status_code=404, detail="Node not found")


@app.delete("/nodes/{node_id}")
def delete_node(node_id: int):
    """
    Delete a worker node by index.
    """
    global worker_nodes
    if 0 <= node_id < len(worker_nodes):
        deleted_node = worker_nodes.pop(node_id)
        return {"message": f"Node {deleted_node.ip} deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Node not found")


@app.post("/nodes/refresh_status", response_model=List[WorkerNode])
def refresh_node_status():
    """
    Re-check connectivity for all known worker nodes.
    """
    global worker_nodes
    updated_nodes: List[WorkerNode] = []

    for node in worker_nodes:
        status, checked_at = _check_node_connectivity(node)
        updated_nodes.append(
            node.copy(update={"status": status, "last_checked": checked_at})
        )

    worker_nodes = updated_nodes
    return worker_nodes


def _airflow_client() -> httpx.Client:
    return httpx.Client(
        base_url=AIRFLOW_BASE_URL.rstrip("/"),
        auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD),
        timeout=10.0,
    )


def _get_dag_run_state(run_id: str) -> Optional[str]:
    try:
        with _airflow_client() as client:
            resp = client.get(f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns/{run_id}")
            if resp.is_success:
                return resp.json().get("state")
    except Exception as exc:
        print(f"Warning: failed to fetch dag run state for {run_id}: {exc}")
    return None


def _redact_sensitive_logs(raw_logs: str) -> str:
    # Basic safety redaction before sending logs to LLM providers.
    redacted = re.sub(r"(?i)(password|passwd|token|api[_-]?key|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", raw_logs)
    redacted = re.sub(r"(?i)authorization:\s*bearer\s+\S+", "authorization: bearer [REDACTED]", redacted)
    return redacted


def _summarize_logs_with_llm(run_id: Optional[str], status: Optional[str], logs: str) -> LogSummaryResponse:
    safe_logs = _redact_sensitive_logs(logs)
    structured_context, failed_tasks, successful_tasks = build_llm_log_context(safe_logs)
    # Keep payload bounded for cost and latency.
    if len(structured_context) > 12000:
        structured_context = structured_context[-12000:]

    if not LLM_API_KEY:
        summary = (
            "Deployment logs processed using fallback mode. "
            f"Detected failed tasks: {', '.join(failed_tasks) if failed_tasks else 'none'}."
        )
        actions = [f"Review failure evidence for {task} and run Agent Ops analysis." for task in failed_tasks[:8]]
        return LogSummaryResponse(
            summary=summary,
            executed_steps=successful_tasks[:10],
            security_suggestions=["Configure LLM_API_KEY to enable richer log summaries."],
            root_causes=failed_tasks[:6],
            recommended_actions=actions,
            confidence="low",
        )

    system_prompt = (
        "You are a DevOps log analyst. Return strict JSON with keys: "
        "summary (string), executed_steps (array of strings), security_suggestions (array of strings), "
        "root_causes (array of strings), recommended_actions (array of strings), confidence (low|medium|high). "
        "When status is success/completed, keep root_causes minimal and focus on executed_steps + security_suggestions. "
        "When multiple tasks are present, return one root cause per failed task when possible. "
        "If there are N failed tasks, root_causes should ideally contain N entries and recommended_actions should ideally contain N entries. "
        "Do not treat security warnings as executed steps. "
        "Do not include markdown."
    )
    user_prompt = (
        f"Run ID: {run_id or '-'}\n"
        f"Status: {status or '-'}\n"
        f"Failed tasks: {failed_tasks or ['none']}\n"
        f"Successful tasks: {successful_tasks or ['none']}\n"
        "Analyze these deployment task results. Base the answer on the structured task evidence below. "
        "Mention all failed tasks. If a task is simulated/demo-like, still report the technical failure accurately.\n\n"
        f"{structured_context}"
    )

    try:
        with httpx.Client(base_url=LLM_BASE_URL.rstrip("/"), timeout=30.0) as client:
            resp = client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            if not resp.is_success:
                raise HTTPException(status_code=502, detail=f"LLM API error: {resp.status_code} {resp.text}")
            data = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Unable to reach LLM API: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
        import json

        parsed = json.loads(content)
        return LogSummaryResponse(
            summary=str(parsed.get("summary", "")).strip(),
            executed_steps=[str(x).strip() for x in parsed.get("executed_steps", [])][:10],
            security_suggestions=[str(x).strip() for x in parsed.get("security_suggestions", [])][:10],
            root_causes=[str(x).strip() for x in parsed.get("root_causes", [])][:6],
            recommended_actions=[str(x).strip() for x in parsed.get("recommended_actions", [])][:8],
            confidence=str(parsed.get("confidence", "medium")).strip().lower(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Invalid LLM response format: {exc}") from exc


def _analyze_failed_run_with_agents(run_id: str, status: str, logs: str) -> dict:
    if not logs or not logs.strip():
        raise HTTPException(status_code=400, detail="No logs provided")

    failure_payloads = build_agent_failure_payloads(logs)
    if not failure_payloads:
        raise HTTPException(status_code=400, detail="Unable to identify a failed task from the provided logs")

    try:
        with httpx.Client(timeout=60.0) as client:
            analyses = []

            for failure_payload in failure_payloads:
                payload = {
                    "dag_id": AIRFLOW_DAG_ID,
                    "dag_run_id": run_id,
                    "failed_task": failure_payload.failed_task,
                    "task_state": failure_payload.task_state,
                    "log_text": failure_payload.log_text,
                    "timestamp": failure_payload.timestamp or datetime.utcnow().isoformat(),
                }

                resp = client.post(AGENT_OPS_API_URL, json=payload)
                if not resp.is_success:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Agent Ops API error: {resp.status_code} {resp.text}",
                    )

                analysis = resp.json()
                analysis["analysis_task_id"] = failure_payload.failed_task
                analyses.append(analysis)

            severity_rank = {"critical": 3, "high": 2, "low": 1}
            analyses.sort(
                key=lambda item: (
                    -severity_rank.get(str(item.get("combined_summary", {}).get("severity", "")).lower(), 0),
                    str(item.get("combined_summary", {}).get("failed_task") or item.get("analysis_task_id") or ""),
                )
            )

            failed_tasks = [
                item.get("combined_summary", {}).get("failed_task") or item.get("analysis_task_id")
                for item in analyses
            ]
            highest_severity = next(
                (
                    item.get("combined_summary", {}).get("severity")
                    for item in analyses
                    if item.get("combined_summary", {}).get("severity")
                ),
                "unknown",
            )

            return {
                "pipeline_status": "alerted",
                "dag_run_id": run_id,
                "failure_detected": True,
                "failed_task_count": len(analyses),
                "failed_tasks": failed_tasks,
                "highest_severity": highest_severity,
                "analyses": analyses,
            }
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Unable to reach Agent Ops API: {exc}") from exc


@app.post("/deployments/start", response_model=DeploymentStartResponse)
def start_deployment():
    """
    Trigger Airflow DAG run via Airflow REST API.
    """
    # Check if we have reachable nodes
    reachable_nodes = [node for node in worker_nodes if node.status == "reachable"]
    
    if not reachable_nodes:
        raise HTTPException(
            status_code=400,
            detail="No reachable worker nodes available. Please add and configure worker nodes first."
        )
    
    run_id = f"manual__{datetime.utcnow().isoformat()}"
    payload = {
        "dag_run_id": run_id,
        "conf": {
            "worker_nodes": [
                {
                    "ip": node.ip,
                    "username": node.username,
                    "password": node.password
                } for node in reachable_nodes
            ]
        },
    }
    
    try:
        with _airflow_client() as client:
            resp = client.post(f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns", json=payload)
            if resp.status_code not in (200, 201):
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to trigger DAG: {resp.status_code} {resp.text}",
                )
            data = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Error reaching Airflow: {exc}") from exc

    # Start direct log monitoring
    dag_run_id = data.get("dag_run_id", run_id)
    print(f"🚀 Starting deployment: {dag_run_id}")
    log_reader.start_monitoring(AIRFLOW_DAG_ID, dag_run_id)

    state = data.get("state")
    return DeploymentStartResponse(
        run_id=dag_run_id, 
        state=state,
        message=f"Airflow deployment started on {len(reachable_nodes)} worker nodes"
    )


@app.get("/deployments/{run_id}/logs/{task_id}", response_model=DeploymentLogResponse)
def get_deployment_logs(run_id: str, task_id: str):
    """
    Fetch task logs and state for a given DAG run + task from Airflow.
    """
    print(f"🔍 Fetching logs for run_id={run_id}, task_id={task_id}")
    print(f"🔗 Airflow URL: {AIRFLOW_BASE_URL}")
    
    try:
        with _airflow_client() as client:
            print(f"📡 Getting task instance for {task_id}")
            ti_resp = client.get(
                f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}"
            )
            print(f"📊 Task instance response: {ti_resp.status_code}")
            
            if ti_resp.status_code == 404:
                print(f"❌ Task instance not found: {task_id}")
                raise HTTPException(status_code=404, detail=f"Task instance not found: {task_id}")
            if not ti_resp.is_success:
                print(f"❌ Failed to fetch task instance: {ti_resp.status_code} {ti_resp.text}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch task instance: {ti_resp.status_code} {ti_resp.text}",
                )
            ti_data = ti_resp.json()
            state = ti_data.get("state")
            print(f"✅ Task state: {state}")

            print(f"📄 Getting logs for {task_id}")
            log_resp = client.get(
                f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}/logs/1"
            )
            print(f"📊 Log response: {log_resp.status_code}")
            
            if not log_resp.is_success:
                print(f"❌ Failed to fetch logs: {log_resp.status_code} {log_resp.text}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch logs: {log_resp.status_code} {log_resp.text}",
                )
            # Airflow may return text/plain or JSON depending on version/config.
            content_type = log_resp.headers.get("Content-Type", "")
            print(f"📋 Content-Type: {content_type}")
            if "application/json" in content_type:
                log_data = log_resp.json()
                print(f"📄 JSON log data keys: {list(log_data.keys()) if isinstance(log_data, dict) else 'Not a dict'}")
            else:
                log_data = {"content": log_resp.text}
                print(f"📄 Text log content length: {len(log_resp.text)}")
                
    except httpx.RequestError as exc:
        print(f"❌ Error reaching Airflow: {exc}")
        raise HTTPException(status_code=502, detail=f"Error reaching Airflow: {exc}") from exc

    raw_log = ""
    if isinstance(log_data, dict):
        if "content" in log_data:
            raw_log = log_data["content"]
        elif "logs" in log_data and isinstance(log_data["logs"], list):
            raw_log = "\n".join(str(part) for part in log_data["logs"])
    else:
        raw_log = str(log_data)
    
    print(f"📝 Log content length: {len(raw_log)}")
    if raw_log.strip():
        print(f"📝 Log preview: {raw_log[:100]}...")
    else:
        print(f"⚠️  No log content found")

    return DeploymentLogResponse(run_id=run_id, task_id=task_id, state=state, log=raw_log)


@app.get("/deployments/{run_id}/logs/{task_id}/direct", response_model=DeploymentLogResponse)
def get_deployment_logs_direct(run_id: str, task_id: str):
    """
    Fetch task logs directly from disk in real-time.
    """
    print(f"🔍 Direct log request: run_id={run_id}, task_id={task_id}")
    
    # Get logs from direct reader
    logs = log_reader.get_logs(task_id)
    
    if logs:
        print(f"📝 Found {len(logs)} chars of logs for {task_id}")
        print(f"📝 Preview: {logs[:100]}...")
        
        # Determine state from logs (simple heuristic)
        state = "running"
        if "Task exited with return code 0" in logs:
            state = "success"
        elif "Task failed" in logs or "ERROR" in logs:
            state = "failed"
        
        return DeploymentLogResponse(run_id=run_id, task_id=task_id, state=state, log=logs)
    else:
        print(f"⚠️  No logs found for {task_id}")
        return DeploymentLogResponse(run_id=run_id, task_id=task_id, state="running", log="")


@app.get("/deployments/{run_id}/live-logs", response_model=DeploymentLiveLogResponse)
def get_deployment_logs_live(run_id: str):
    """
    Return combined real-time logs for all tasks in a DAG run.
    """
    combined_logs, task_streams = log_reader.get_combined_logs_for_run(AIRFLOW_DAG_ID, run_id)
    if not combined_logs:
        combined_logs = log_reader.get_combined_logs()
        task_streams = len(log_reader.get_all_logs())
    state = _get_dag_run_state(run_id) or "running"

    return DeploymentLiveLogResponse(
        run_id=run_id,
        state=state,
        log=combined_logs,
        task_streams=task_streams,
    )


@app.post("/logs/summarize-llm", response_model=LogSummaryResponse)
def summarize_logs_llm(payload: LogSummaryRequest):
    if not payload.logs or not payload.logs.strip():
        raise HTTPException(status_code=400, detail="No logs provided")
    return _summarize_logs_with_llm(payload.run_id, payload.status, payload.logs)


@app.post("/agent-ops/analyze")
def analyze_agent_ops(payload: AgentOpsAnalyzeRequest):
    return _analyze_failed_run_with_agents(payload.run_id, payload.status, payload.logs)
