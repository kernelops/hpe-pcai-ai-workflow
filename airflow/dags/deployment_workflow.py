from datetime import datetime

import requests
from airflow import DAG
from airflow.models import Connection
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.utils.session import provide_session
from airflow.utils.trigger_rule import TriggerRule

API_BASE = "http://host.docker.internal:8000"


def get_worker_nodes(**context):
    """Fetch reachable worker nodes from backend API."""
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
    dag_id="deployment_workflow",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["deployment", "error-simulation"],
) as dag:
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )

    simulate_os_validation_error = SSHOperator.partial(
        task_id="simulate_os_validation_error",
        command=(
            "set -e; "
            "echo 'Simulating realistic OS validation failure...'; "
            "uname -a; "
            "id; "
            "echo 'Expecting RHEL-style baseline validation on a non-RHEL host...'; "
            "test -f /etc/redhat-release || "
            "(echo 'OS baseline validation failed: expected /etc/redhat-release on target host' >&2; exit 1)"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_nfs_configuration_error = SSHOperator.partial(
        task_id="simulate_nfs_configuration_error",
        command=(
            "set -e; "
            "echo 'Simulating realistic NFS configuration failure...'; "
            "sudo mkdir -p /srv/nfs/share; "
            "printf '%s\n' '/srv/nfs/share *(rw,sync,broken_option)' | sudo tee /etc/exports >/dev/null; "
            "sudo exportfs -ra"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_minio_service_error = SSHOperator.partial(
        task_id="simulate_minio_service_error",
        command=(
            "set -e; "
            "echo 'Simulating realistic MinIO service failure...'; "
            "sudo systemctl enable --now minio-broken"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_postcheck_error = SSHOperator.partial(
        task_id="simulate_postcheck_error",
        command=(
            "set -e; "
            "echo 'Simulating realistic post-deployment validation failure...'; "
            "curl -fsS http://127.0.0.1:9005/minio/health/live"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    simulation_complete = EmptyOperator(
        task_id="simulation_complete",
        trigger_rule=TriggerRule.ALL_DONE,
    )

    get_nodes >> create_connections
    create_connections >> simulate_os_validation_error >> simulation_complete
    create_connections >> simulate_nfs_configuration_error >> simulation_complete
    create_connections >> simulate_minio_service_error >> simulation_complete
    create_connections >> simulate_postcheck_error >> simulation_complete
