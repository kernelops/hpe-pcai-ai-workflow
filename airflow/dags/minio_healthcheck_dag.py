"""
minio_health_check_dag.py

A  DAG that checks MinIO health on a worker node.
The DAG itself is perfect — any failure is purely environmental.

Error triggered: curl: (7) Failed to connect to localhost port 9000: Connection refused

Possible causes:
1. MinIO was never started
2. MinIO started but crashed/terminated unexpectedly
3. MinIO is listening on a different port
4. Firewall blocking port 9000
"""
import os
import requests
from datetime import datetime
from airflow import DAG
from airflow.models import Connection
from airflow.utils.session import provide_session
from airflow.operators.python import PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator

API_BASE = os.getenv("BACKEND_API_BASE", "http://localhost:8000")

def get_worker_nodes(**context):
    """Fetch worker nodes from DAG conf first, then fall back to backend API."""
    dag_run = context.get("dag_run")
    dag_conf = dag_run.conf or {} if dag_run else {}
    conf_nodes = dag_conf.get("worker_nodes") or []

    if conf_nodes:
        reachable = [n for n in conf_nodes if n.get("ip") and n.get("username")]
        print(f"Using {len(reachable)} worker nodes from dag_run conf")
        for node in reachable:
            print(f" - {node['ip']} ({node['username']})")
        return reachable

    try:
        response = requests.get(f"{API_BASE}/nodes", timeout=15)
        response.raise_for_status()
        nodes = response.json()

        reachable = [n for n in nodes if n.get("status") == "reachable"]

        print(f"Found {len(reachable)} reachable nodes")
        for node in reachable:
            print(f" - {node['ip']} ({node['username']})")

        return reachable
    except Exception as exc:
        print(f"Error fetching nodes: {exc}")
        return []

@provide_session
def create_airflow_connections(session=None, **context):
    """Create or reuse Airflow SSH connections for worker nodes."""
    nodes = context["task_instance"].xcom_pull(task_ids="get_worker_nodes")
    conn_ids = []

    if not nodes:
        print("No nodes received")
        return conn_ids

    for node in nodes:
        ip = node["ip"]
        username = node["username"]
        password = node.get("password", "")
        conn_id = f"worker_node_{ip.replace('.', '_')}"

        existing = session.query(Connection).filter(Connection.conn_id == conn_id).first()
        if existing:
            print(f"Connection already exists: {conn_id}")
        else:
            session.add(
                Connection(
                    conn_id=conn_id,
                    conn_type="ssh",
                    host=ip,
                    login=username,
                    password=password,
                    port=22,
                )
            )
            session.commit()
            print(f"Created connection for {ip}")

        conn_ids.append(conn_id)

    return conn_ids

with DAG(
    dag_id     = "minio_health_check",
    start_date = datetime(2024, 1, 1),
    schedule   = None,
    catchup    = False,
    tags       = ["minio", "health-check", "phase2"],
) as dag:
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )
    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
    # Task 1: Check MinIO health endpoint
    # This is the task that will fail with: curl: (7) Failed to connect to localhost port 9000: Connection refused
    check_minio_health = SSHOperator.partial(
        task_id     = "check_minio_health",
        command     = ("curl -f http://localhost:9000/minio/health/live"),
        get_pty     = True,
        conn_timeout= 10,
        cmd_timeout = 30,
    ).expand(ssh_conn_id=create_connections.output)

    # Task 2: Only runs if health check passes — verifies MinIO is actually usable
    verify_minio_ready = SSHOperator.partial(
        task_id     = "verify_minio_ready",
        command     = ("curl -f http://localhost:9000/minio/health/cluster"),
        get_pty     = True,
        conn_timeout= 10,
        cmd_timeout = 30,
    ).expand(ssh_conn_id=create_connections.output)

    get_nodes >> create_connections >> check_minio_health >> verify_minio_ready