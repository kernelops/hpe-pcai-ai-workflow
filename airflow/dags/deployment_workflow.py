"""
Corrupted composite deployment DAG for remediation/RAG testing.

This file intentionally borrows the shape of the good MinIO, NFS, and OS
validation workflows, then introduces realistic operational
mistakes. The DAG should parse cleanly, but selected tasks should fail in ways
that a remediation workflow can reconstruct into a working deployment.
"""

import json
import os
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.models import Connection
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.utils.session import provide_session
from airflow.utils.trigger_rule import TriggerRule


API_BASE = os.getenv("BACKEND_API_BASE", "http://host.docker.internal:8000")


default_args = {
    "owner": "infra-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
}


def get_worker_nodes(**context):
    """Fetch worker nodes from DAG conf first, then fall back to backend API."""
    dag_run = context.get("dag_run")
    dag_conf = dag_run.conf or {} if dag_run else {}
    conf_nodes = dag_conf.get("worker_nodes") or []

    if conf_nodes:
        reachable = [node for node in conf_nodes if node.get("ip") and node.get("username")]
        print(f"Using {len(reachable)} worker nodes from dag_run conf")
        return reachable

    try:
        response = requests.get(f"{API_BASE}/nodes", timeout=15)
        response.raise_for_status()
        nodes = response.json()
        reachable = [node for node in nodes if node.get("status") == "reachable"]
        print(f"Found {len(reachable)} reachable nodes")
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


def assign_node_roles(**kwargs):
    nodes = kwargs["ti"].xcom_pull(task_ids="get_worker_nodes")
    if not nodes:
        raise AirflowException("No reachable worker nodes available")

    server_node = nodes[0]
    client_node = nodes[1] if len(nodes) > 1 else nodes[0]
    host_conn_id = f"worker_node_{server_node['ip'].replace('.', '_')}"
    client_conn_id = f"worker_node_{client_node['ip'].replace('.', '_')}"

    print("--- RUNTIME ALLOCATION ---")
    print(f"Allocated NFS/MinIO host: {host_conn_id}")
    print(f"Allocated NFS client: {client_conn_id}")
    print(f"Server host IP: {server_node['ip']}")
    print("--------------------------")

    kwargs["ti"].xcom_push(key="server", value=host_conn_id)
    kwargs["ti"].xcom_push(key="client", value=client_conn_id)
    kwargs["ti"].xcom_push(key="server_host", value=server_node["ip"])


VALIDATION_TASK_IDS = [
    "prepare_nfs_server_storage",
    "verify_nfs_prerequisites_corrupted",
    "simulate_nfs_configuration_error",
    "wait_for_nfs_server_boot_corrupted",
    "create_nfs_client_volume_corrupted",
    "test_nfs_client_mount_corrupted",
    "write_nfs_test_file_corrupted",
    "simulate_minio_service_error",
    "simulate_os_validation_error",
]


def emit_failure_payload(**context):
    dag_run = context["dag_run"]
    failed_tasks = []
    successful_tasks = []

    for task_id in VALIDATION_TASK_IDS:
        current_ti = dag_run.get_task_instance(task_id)
        if current_ti and current_ti.state == "success":
            successful_tasks.append(task_id)
        else:
            failed_tasks.append(task_id)

    payload = {
        "dag_id": dag_run.dag_id,
        "run_id": dag_run.run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "failed_tasks": failed_tasks,
        "successful_tasks": successful_tasks,
        "summary": "Corrupted composite deployment failed as expected for remediation testing",
        "expected_recovery": {
            "nfs": "restore the known-good NFS task sequence, export options, server port, volume device, and client container name",
            "minio": "run MinIO on port 9000 and validate the correct health endpoint",
            "os_validation": "validate portable /etc/os-release instead of a RHEL-only file",
        },
    }

    print("Failure payload for RAG ingestion:")
    print(json.dumps(payload, indent=2, default=str))


with DAG(
    dag_id="deployment_workflow_corrupted_composite",
    default_args=default_args,
    description="Intentionally corrupted MinIO/NFS/OS validation deployment workflow",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["deployment", "corrupted", "rag-test", "remediation"],
) as dag:
    start = EmptyOperator(task_id="start")

    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )

    assign_roles = PythonOperator(
        task_id="assign_roles",
        python_callable=assign_node_roles,
    )

    prepare_nfs_server_storage = SSHOperator.partial(
        task_id="prepare_nfs_server_storage",
        get_pty=True,
        do_xcom_push=True,
        command="""
set -e
echo '[NFS] Preparing server storage from the good workflow.'
mkdir -p /tmp/nfs-server-data
chmod 0777 /tmp/nfs-server-data
test -d /tmp/nfs-server-data
        """,
    ).expand(ssh_conn_id=create_connections.output)

    verify_nfs_prerequisites_corrupted = SSHOperator.partial(
        task_id="verify_nfs_prerequisites_corrupted",
        get_pty=True,
        do_xcom_push=True,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Intentional bug: checking a misspelled native NFS utility.'
command -v exportfss
        """,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_nfs_configuration_error = SSHOperator.partial(
        task_id="simulate_nfs_configuration_error",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Configuring native NFS export with an intentionally invalid option.'
sudo mkdir -p /srv/nfs/share
sudo chmod 0777 /srv/nfs/share
printf '%s\n' '/srv/nfs/share *(rw,sync,broken_option)' | sudo tee /etc/exports >/dev/null
sudo exportfs -ra
        """,
    ).expand(ssh_conn_id=create_connections.output)

    wait_for_nfs_server_boot_corrupted = SSHOperator.partial(
        task_id="wait_for_nfs_server_boot_corrupted",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=45,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Intentional bug: starting a wrong native NFS service unit.'
sudo systemctl enable --now nfs-broken
echo '[NFS] Intentional bug: readiness check waits on port 2050 instead of NFS port 2049.'
for i in $(seq 1 6); do
  if ss -tln | grep -q ':2050'; then
    echo 'NFS server is ready on the expected port.'
    exit 0
  fi
  echo "Waiting for corrupted NFS readiness check... ($i/6)"
  sleep 2
done
echo 'ERROR: NFS readiness check failed on port 2050.'
exit 1
        """,
    ).expand(ssh_conn_id=create_connections.output)

    create_nfs_client_volume_corrupted = SSHOperator.partial(
        task_id="create_nfs_client_volume_corrupted",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=45,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Intentional bug: native client mount points at the wrong exported path.'
sudo mkdir -p /mnt/nfs
sudo umount /mnt/nfs 2>/dev/null || true
sudo mount -t nfs -o nolock {{ ti.xcom_pull(task_ids='assign_roles', key='server_host') }}:/srv/nfs/missing /mnt/nfs
        """,
    ).expand(ssh_conn_id=create_connections.output)

    test_nfs_client_mount_corrupted = SSHOperator.partial(
        task_id="test_nfs_client_mount_corrupted",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Intentional bug: mount validation checks the wrong mount point.'
mountpoint -q /mnt/nfs-broken
        """,
    ).expand(ssh_conn_id=create_connections.output)

    write_nfs_test_file_corrupted = SSHOperator.partial(
        task_id="write_nfs_test_file_corrupted",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=30,
        trigger_rule=TriggerRule.ALL_DONE,
        command="""
set -e
echo '[NFS] Intentional bug: write validation targets the wrong mount path.'
echo 'Hello from corrupted NFS validation' | sudo tee /mnt/missing/test_file.txt >/dev/null
        """,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_minio_service_error = SSHOperator.partial(
        task_id="simulate_minio_service_error",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        command="""
set -e
echo '[MINIO] Simulating MinIO service validation without Docker.'
echo '[MINIO] Intentional bug: workflow uses the wrong MinIO systemd unit name.'
sudo systemctl enable --now minio-broken
        """,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_os_validation_error = SSHOperator.partial(
        task_id="simulate_os_validation_error",
        get_pty=True,
        do_xcom_push=True,
        command="""
set -e
echo '[OS] Running intentionally over-specific OS validation.'
uname -a
id
echo '[OS] Intentional bug: expecting a RHEL marker on a generic Ubuntu/Linux host.'
test -f /etc/redhat-release || (echo 'OS baseline validation failed: expected /etc/redhat-release on target host' >&2; exit 1)
        """,
    ).expand(ssh_conn_id=create_connections.output)

    failure_payload = PythonOperator(
        task_id="failure_payload",
        python_callable=emit_failure_payload,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    remediation_input_ready = EmptyOperator(
        task_id="remediation_input_ready",
        trigger_rule=TriggerRule.ALL_DONE,
    )

    start >> get_nodes >> create_connections >> assign_roles
    assign_roles >> prepare_nfs_server_storage >> verify_nfs_prerequisites_corrupted >> simulate_nfs_configuration_error
    simulate_nfs_configuration_error >> wait_for_nfs_server_boot_corrupted >> create_nfs_client_volume_corrupted
    create_nfs_client_volume_corrupted >> test_nfs_client_mount_corrupted >> write_nfs_test_file_corrupted
    write_nfs_test_file_corrupted >> failure_payload
    assign_roles >> simulate_minio_service_error >> failure_payload
    assign_roles >> simulate_os_validation_error >> failure_payload
    failure_payload >> remediation_input_ready
