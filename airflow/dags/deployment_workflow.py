import os
from datetime import datetime

import paramiko
import requests
from airflow import DAG
from airflow.models import Connection
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.utils.session import provide_session
from airflow.utils.trigger_rule import TriggerRule

API_BASE = os.getenv("BACKEND_API_BASE", "http://host.docker.internal:8000")
NFS_MOUNT_POINT = os.getenv("NFS_MOUNT_POINT", "/mnt/nfs")
NFS_A_EXPORT_DIR = os.getenv("NFS_A_EXPORT_DIR", "/srv/nfs_a/shared")
NFS_B_EXPORT_DIR = os.getenv("NFS_B_EXPORT_DIR", "/srv/nfs_b/shared")


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


def _run_node_command(node: dict, command: str) -> str:
    """Run a shell command on a worker node using the stored SSH credentials."""
    ip = node["ip"]
    username = node["username"]
    password = node.get("password", "")

    print(f"Running on {ip}: {command}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ip,
            username=username,
            password=password,
            timeout=20,
            look_for_keys=False,
            allow_agent=False,
        )
        stdin, stdout, stderr = client.exec_command(command, get_pty=True, timeout=120)
        if "sudo" in command and password:
            stdin.write(password + "\n")
            stdin.flush()

        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")

        if out.strip():
            print(out)
        if err.strip():
            print(err)
        if exit_code != 0:
            raise RuntimeError(f"Command failed on {ip} with exit code {exit_code}: {err or out}")
        return out
    finally:
        client.close()


def _require_nodes(**context) -> list[dict]:
    nodes = context["task_instance"].xcom_pull(task_ids="get_worker_nodes") or []
    if len(nodes) < 1:
        raise RuntimeError("Deployment workflow requires at least one reachable worker node")
    return nodes


def prepare_host_nfs_servers(**context):
    """
    Configure one host NFS export on each worker.
    Worker 1 becomes NFS A. If Worker 2 exists, it becomes NFS B.
    """
    nodes = _require_nodes(**context)
    exports = []

    for index, node in enumerate(nodes[:2], start=1):
        ip_parts = node["ip"].split(".")
        permitted_subnet = ".".join(ip_parts[:3]) + ".0/24" if len(ip_parts) == 4 else "*"
        export_dir = NFS_A_EXPORT_DIR if index == 1 else NFS_B_EXPORT_DIR
        export = f"{node['ip']}:{export_dir}"
        exports.append(export)
        command = (
            "set -e; "
            "if ! command -v exportfs >/dev/null 2>&1 || ! command -v mount.nfs >/dev/null 2>&1; then "
            "  echo 'NFS server not installed!' >&2; exit 1; "
            "fi; "
            f"sudo mkdir -p {export_dir}; "
            f"sudo chmod 777 {export_dir}; "
            f"EXPORT_LINE='{export_dir} {permitted_subnet}(rw,sync,no_subtree_check,no_root_squash,insecure)'; "
            "sudo sed -i '/broken_option/d' /etc/exports; "
            f"sudo sed -i '\\#{export_dir} #d' /etc/exports; "
            "printf '%s\\n' \"$EXPORT_LINE\" | sudo tee -a /etc/exports >/dev/null; "
            "sudo exportfs -ra; "
            "sudo systemctl enable --now nfs-server >/dev/null 2>&1 || "
            "sudo systemctl enable --now nfs-kernel-server >/dev/null 2>&1 || true; "
            "sudo systemctl restart nfs-server >/dev/null 2>&1 || "
            "sudo systemctl restart nfs-kernel-server >/dev/null 2>&1 || true; "
            "sudo exportfs -v; "
            f"printf '%s\\n' '{export}' | sudo tee /tmp/pcai_nfs_{index}_export >/dev/null; "
            f"printf '%s\\n' '{exports[0] if exports else export}' | sudo tee /tmp/pcai_nfs_a_export >/dev/null; "
            "sleep 2"
        )
        _run_node_command(node, command)

    # Ensure exports array has at least 2 elements for the return dict
    if len(exports) == 1:
        exports.append(exports[0])

    for index, node in enumerate(nodes[:2]):
        _run_node_command(
            node,
            f"printf '%s\\n' '{exports[0]}' | sudo tee /tmp/pcai_nfs_a_export >/dev/null; "
            f"printf '%s\\n' '{exports[1]}' | sudo tee /tmp/pcai_nfs_b_export >/dev/null",
        )

    print(f"NFS A export: {exports[0]}")
    print(f"NFS B export: {exports[1]}")
    return {"nfs_a_export": exports[0], "nfs_b_export": exports[1]}


def mount_workers_to_nfs_a(**context):
    """Put both workers into the initial healthy state: both mounted to NFS A."""
    nodes = _require_nodes(**context)
    exports = context["task_instance"].xcom_pull(task_ids="prepare_host_nfs_servers")
    nfs_a = exports["nfs_a_export"]

    for node in nodes[:2]:
        command = (
            "set -e; "
            "if ! command -v mount.nfs >/dev/null 2>&1; then "
            "  echo 'NFS common not installed!' >&2; exit 1; "
            "fi; "
            f"sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"sudo rmdir {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"sudo mkdir -p {NFS_MOUNT_POINT}; "
            f"(timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 {nfs_a} {NFS_MOUNT_POINT} || "
            f"(sleep 2; sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 {nfs_a} {NFS_MOUNT_POINT})); "
            f"printf '%s\\n' '{nfs_a}' | sudo tee /tmp/pcai_nfs_a_export >/dev/null; "
            f"mount | grep ' {NFS_MOUNT_POINT} '"
        )
        _run_node_command(node, command)


def create_nfs_validation_file(**context):
    """Write the validation file on Worker 1, which is mounted to NFS A."""
    nodes = _require_nodes(**context)
    command = (
        "set -e; "
        f"printf '%s\\n' 'deployment-check' | sudo tee {NFS_MOUNT_POINT}/check.txt >/dev/null; "
        f"cat {NFS_MOUNT_POINT}/check.txt; "
        f"mount | grep ' {NFS_MOUNT_POINT} '"
    )
    _run_node_command(nodes[0], command)


def simulate_nfs_mount_inconsistency(**context):
    """Move Worker 2 from NFS A to NFS B (or unmount if 1 node), creating the environment issue."""
    nodes = _require_nodes(**context)
    exports = context["task_instance"].xcom_pull(task_ids="prepare_host_nfs_servers")
    
    if len(nodes) == 1:
        # For 1 node, we just unmount it to simulate the file missing
        command = (
            "set -e; "
            f"sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            "echo 'NFS mount inconsistency injected: Worker 1 unmounted from NFS A'; "
        )
        _run_node_command(nodes[0], command)
    else:
        nfs_b = exports["nfs_b_export"]
        command = (
            "set -e; "
            "sudo exportfs -ra; "
            "sudo systemctl restart nfs-server >/dev/null 2>&1 || "
            "sudo systemctl restart nfs-kernel-server >/dev/null 2>&1 || true; "
            "sudo exportfs -ra; "
            f"sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"sudo rmdir {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"sudo mkdir -p {NFS_MOUNT_POINT}; "
            f"(timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 {nfs_b} {NFS_MOUNT_POINT} || "
            f"(sleep 2; sudo exportfs -ra; sudo umount -lf {NFS_MOUNT_POINT} >/dev/null 2>&1 || true; "
            f"timeout 20 sudo mount -t nfs -o vers=3,nolock,timeo=5,retrans=1 {nfs_b} {NFS_MOUNT_POINT})); "
            f"printf '%s\\n' '{nfs_b}' | sudo tee /tmp/pcai_nfs_b_export >/dev/null; "
            "echo 'NFS mount inconsistency injected: Worker 2 now points to NFS B'; "
            f"mount | grep ' {NFS_MOUNT_POINT} '"
        )
        _run_node_command(nodes[1], command)


def validate_nfs_consistency(**context):
    """
    Validate from the target worker (Worker 2 if available, or Worker 1).
    This fails because the target worker cannot read check.txt anymore.
    """
    nodes = _require_nodes(**context)
    target_node = nodes[-1] if len(nodes) > 1 else nodes[0]
    
    command = (
        "set -e; "
        f"echo 'Validating NFS consistency'; "
        f"mount | grep ' {NFS_MOUNT_POINT} ' || true; "
        f"test -f {NFS_MOUNT_POINT}/check.txt || "
        f"(echo 'NFS consistency validation failed: {NFS_MOUNT_POINT}/check.txt missing on worker node. "
        "Possible NFS mount inconsistency between worker nodes.' >&2; exit 1); "
        f"grep -qx 'deployment-check' {NFS_MOUNT_POINT}/check.txt"
    )
    _run_node_command(target_node, command)


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
            "sudo rm -f /etc/redhat-release; "
            "echo 'Expecting RHEL-style baseline validation on a non-RHEL host...'; "
            "test -f /etc/redhat-release || "
            "(echo 'OS baseline validation failed: expected /etc/redhat-release on target host' >&2; exit 1)"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    simulate_minio_service_error = SSHOperator.partial(
        task_id="simulate_minio_service_error",
        command=(
            "set -e; "
            "echo 'Simulating realistic MinIO service failure...'; "
            "sudo systemctl disable --now minio-broken >/dev/null 2>&1 || true; "
            "sudo rm -f /etc/systemd/system/minio-broken.service; "
            "sudo systemctl daemon-reload; "
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
            "sudo fuser -k 9005/tcp >/dev/null 2>&1 || true; "
            "curl -fsS http://127.0.0.1:9005/minio/health/live"
        ),
        get_pty=True,
        do_xcom_push=True,
    ).expand(ssh_conn_id=create_connections.output)

    prepare_nfs = PythonOperator(
        task_id="prepare_host_nfs_servers",
        python_callable=prepare_host_nfs_servers,
    )

    mount_nfs_a = PythonOperator(
        task_id="mount_workers_to_nfs_a",
        python_callable=mount_workers_to_nfs_a,
    )

    create_nfs_file = PythonOperator(
        task_id="create_nfs_validation_file",
        python_callable=create_nfs_validation_file,
    )

    inject_nfs_drift = PythonOperator(
        task_id="simulate_nfs_mount_inconsistency",
        python_callable=simulate_nfs_mount_inconsistency,
    )

    validate_nfs = PythonOperator(
        task_id="validate_nfs_consistency",
        python_callable=validate_nfs_consistency,
    )

    simulation_complete = EmptyOperator(
        task_id="simulation_complete",
        trigger_rule=TriggerRule.ALL_DONE,
    )

    get_nodes >> create_connections
    create_connections >> simulate_os_validation_error >> simulation_complete
    create_connections >> simulate_minio_service_error >> simulation_complete
    create_connections >> simulate_postcheck_error >> simulation_complete
    (
        create_connections
        >> prepare_nfs
        >> mount_nfs_a
        >> create_nfs_file
        >> inject_nfs_drift
        >> validate_nfs
        >> simulation_complete
    )
