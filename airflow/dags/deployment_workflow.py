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
    "verify_nfs_prerequisites",
    "configure_nfs_export",
    "wait_for_nfs_server_boot",
    "mount_nfs_client_share",
    "test_nfs_client_mount",
    "write_nfs_test_file",
    "install_and_configure_minio",
    "validate_minio_service",
]


def emit_success_payload(**context):
    dag_run = context["dag_run"]
    task_states = {}

    for task_id in VALIDATION_TASK_IDS:
        current_ti = dag_run.get_task_instance(task_id)
        task_states[task_id] = current_ti.state if current_ti else "not_found"

    payload = {
        "dag_id": dag_run.dag_id,
        "run_id": dag_run.run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "task_states": task_states,
        "summary": "Deployment validation and installation completed",
    }

    print("Deployment payload:")
    print(json.dumps(payload, indent=2, default=str))


with DAG(
    dag_id="deployment_workflow",
    default_args=default_args,
    description="MinIO/NFS deployment and validation workflow",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["deployment", "good", "validation"],
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
echo '[NFS] Preparing native NFS server storage.'
sudo mkdir -p /srv/nfs/share
sudo chmod 0777 /srv/nfs/share
test -d /srv/nfs/share
        """,
    ).expand(ssh_conn_id=create_connections.output)

    verify_nfs_prerequisites = SSHOperator.partial(
        task_id="verify_nfs_prerequisites",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=300,
        command="""
set -e
echo '[NFS] Ensuring native NFS packages are available.'
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nfs-kernel-server nfs-common
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y nfs-utils
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y nfs-utils
fi
command -v exportfs
command -v mount.nfs
        """,
    ).expand(ssh_conn_id=create_connections.output)

    configure_nfs_export = SSHOperator.partial(
        task_id="configure_nfs_export",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        command="""
set -e
echo '[NFS] Configuring native NFS export.'
sudo mkdir -p /srv/nfs/share
sudo chmod 0777 /srv/nfs/share
printf '%s\n' '/srv/nfs/share *(rw,sync,no_subtree_check,no_root_squash)' | sudo tee /etc/exports >/dev/null
sudo exportfs -ra
sudo exportfs -v
        """,
    ).expand(ssh_conn_id=create_connections.output)

    wait_for_nfs_server_boot = SSHOperator.partial(
        task_id="wait_for_nfs_server_boot",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=90,
        command="""
set -e
echo '[NFS] Starting native NFS service and checking port 2049.'
if systemctl list-unit-files | grep -q '^nfs-server.service'; then
  sudo systemctl enable --now nfs-server
else
  sudo systemctl enable --now nfs-kernel-server
fi
for i in $(seq 1 10); do
  if ss -tln | grep -q ':2049'; then
    echo 'NFS server is ready on port 2049.'
    exit 0
  fi
  echo "Waiting for NFS server readiness... ($i/10)"
  sleep 2
done
echo 'ERROR: NFS readiness check failed on port 2049.'
exit 1
        """,
    ).expand(ssh_conn_id=create_connections.output)

    mount_nfs_client_share = SSHOperator.partial(
        task_id="mount_nfs_client_share",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        command="""
set -e
echo '[NFS] Mounting native NFS share on client.'
sudo mkdir -p /mnt/nfs
sudo umount /mnt/nfs 2>/dev/null || true
sudo mount -t nfs4 -o nolock {{ ti.xcom_pull(task_ids='assign_roles', key='server_host') }}:/srv/nfs/share /mnt/nfs
        """,
    ).expand(ssh_conn_id=create_connections.output)

    test_nfs_client_mount = SSHOperator.partial(
        task_id="test_nfs_client_mount",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        command="""
set -e
echo '[NFS] Validating native NFS mount point.'
mountpoint -q /mnt/nfs
mount | grep /mnt/nfs
        """,
    ).expand(ssh_conn_id=create_connections.output)

    write_nfs_test_file = SSHOperator.partial(
        task_id="write_nfs_test_file",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=30,
        command="""
set -e
echo '[NFS] Writing validation file through NFS mount.'
echo 'NFS remediation OK' | sudo tee /mnt/nfs/test_file.txt >/dev/null
cat /mnt/nfs/test_file.txt
        """,
    ).expand(ssh_conn_id=create_connections.output)

    install_and_configure_minio = SSHOperator.partial(
        task_id="install_and_configure_minio",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=600,
        command="""
set -e
echo '[MINIO] Checking if MinIO is installed...'
if ! command -v minio >/dev/null 2>&1; then
  echo '[MINIO] Downloading and Installing MinIO...'
  sudo wget -q https://dl.min.io/server/minio/release/linux-amd64/minio -O /usr/local/bin/minio
  sudo chmod +x /usr/local/bin/minio
fi

echo '[MINIO] Configuring MinIO data directory...'
sudo mkdir -p /srv/minio/data
sudo chmod 0777 /srv/minio/data

echo '[MINIO] Setting up MinIO service...'
cat << 'SERVICEEOF' | sudo tee /etc/systemd/system/minio.service >/dev/null
[Unit]
Description=MinIO
Documentation=https://min.io/docs/minio/linux/index.html
Wants=network-online.target
After=network-online.target

[Service]
Environment="MINIO_ROOT_USER=admin"
Environment="MINIO_ROOT_PASSWORD=password"
ExecStart=/usr/local/bin/minio server /srv/minio/data --console-address ":9001"
Restart=always
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SERVICEEOF

sudo systemctl daemon-reload
sudo systemctl enable --now minio
        """,
    ).expand(ssh_conn_id=create_connections.output)

    validate_minio_service = SSHOperator.partial(
        task_id="validate_minio_service",
        get_pty=True,
        do_xcom_push=True,
        cmd_timeout=60,
        command="""
set -e
echo '[MINIO] Validating MinIO service is active...'
systemctl is-active --quiet minio
echo '[MINIO] minio.service is active and running.'
        """,
    ).expand(ssh_conn_id=create_connections.output)

    success_payload = PythonOperator(
        task_id="success_payload",
        python_callable=emit_success_payload,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    deployment_validated = EmptyOperator(
        task_id="deployment_validated",
        trigger_rule=TriggerRule.ALL_DONE,
    )

    start >> get_nodes >> create_connections >> assign_roles
    assign_roles >> prepare_nfs_server_storage >> verify_nfs_prerequisites >> configure_nfs_export
    configure_nfs_export >> wait_for_nfs_server_boot >> mount_nfs_client_share
    mount_nfs_client_share >> test_nfs_client_mount >> write_nfs_test_file
    write_nfs_test_file >> success_payload
    
    assign_roles >> install_and_configure_minio >> validate_minio_service >> success_payload
    
    success_payload >> deployment_validated

