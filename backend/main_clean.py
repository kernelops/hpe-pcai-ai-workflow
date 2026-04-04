import os
import socket
from typing import List, Literal, Optional
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime


AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL", "http://localhost:8080")
AIRFLOW_DAG_ID = os.getenv("AIRFLOW_DAG_ID", "deployment_workflow")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME", "airflow")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "airflow")


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
    Simple and reliable connectivity check.
    """
    status: Literal["reachable", "unreachable"] = "unreachable"
    now = datetime.utcnow()
    
    print(f"Checking connectivity to {node.ip}...")
    
    # Simple TCP connection test to port 22
    try:
        with socket.create_connection((node.ip, 22), timeout=3):
            status = "reachable"
            print(f"✓ Successfully connected to {node.ip}:22")
    except socket.timeout:
        print(f"✗ Timeout connecting to {node.ip}:22")
        status = "unreachable"
    except ConnectionRefusedError:
        print(f"✗ Connection refused by {node.ip}:22")
        status = "unreachable"
    except OSError as e:
        print(f"✗ Network error to {node.ip}: {e}")
        status = "unreachable"
    except Exception as e:
        print(f"✗ Unexpected error to {node.ip}: {e}")
        status = "unreachable"
    
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
            import socket
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

    state = data.get("state")
    return DeploymentStartResponse(
        run_id=data.get("dag_run_id", run_id), 
        state=state,
        message=f"Airflow deployment started on {len(reachable_nodes)} worker nodes"
    )


@app.get("/deployments/{run_id}/logs/{task_id}", response_model=DeploymentLogResponse)
def get_deployment_logs(run_id: str, task_id: str):
    """
    Fetch task logs and state for a given DAG run + task from Airflow.
    """
    try:
        with _airflow_client() as client:
            ti_resp = client.get(
                f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}"
            )
            if ti_resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Task instance not found")
            if not ti_resp.is_success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch task instance: {ti_resp.status_code} {ti_resp.text}",
                )
            ti_data = ti_resp.json()
            state = ti_data.get("state")

            log_resp = client.get(
                f"/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}/logs/1"
            )
            if not log_resp.is_success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch logs: {log_resp.status_code} {log_resp.text}",
                )
            # Airflow may return text/plain or JSON depending on version/config.
            content_type = log_resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                log_data = log_resp.json()
            else:
                log_data = {"content": log_resp.text}
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Error reaching Airflow: {exc}") from exc

    raw_log = ""
    if isinstance(log_data, dict):
        if "content" in log_data:
            raw_log = log_data["content"]
        elif "logs" in log_data and isinstance(log_data["logs"], list):
            raw_log = "\n".join(str(part) for part in log_data["logs"])
    else:
        raw_log = str(log_data)

    return DeploymentLogResponse(run_id=run_id, task_id=task_id, state=state, log=raw_log)
