"""
test_ssh_dag.py
Simple diagnostic DAG to verify SSH connectivity to a worker node.

Hardcodes IP, username, and password directly.
Creates a test file on the remote node to confirm commands are actually executing.

Usage:
    1. Fill in TARGET_IP, TARGET_USERNAME, TARGET_PASSWORD below
    2. Drop this file in your Airflow dags/ folder
    3. Trigger it manually from the Airflow UI
    4. SSH into your worker node and check: ls ~/airflow_test.txt
"""

from datetime import datetime
from airflow import DAG
from airflow.models import Connection
from airflow.utils.session import provide_session
from airflow.operators.python import PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator

# ── Fill these in ──────────────────────────────────────────────
TARGET_IP       = "192.168.1.6"   # your Kali/Ubuntu IP
TARGET_USERNAME = "nikitha"
TARGET_PASSWORD = "ubuntu"
# ──────────────────────────────────────────────────────────────

CONN_ID = "test_worker_node"


@provide_session
def create_test_connection(session=None, **context):
    """Create (or recreate) the SSH connection for the test node."""
    existing = session.query(Connection).filter(Connection.conn_id == CONN_ID).first()
    if existing:
        session.delete(existing)
        session.commit()
        print(f"[Setup] Deleted existing connection: {CONN_ID}")

    session.add(Connection(
        conn_id   = CONN_ID,
        conn_type = "ssh",
        host      = TARGET_IP,
        login     = TARGET_USERNAME,
        password  = TARGET_PASSWORD,
        port      = 22,
    ))
    session.commit()
    print(f"[Setup] Created SSH connection → {TARGET_USERNAME}@{TARGET_IP}:22")


with DAG(
    dag_id   = "test_ssh_connectivity",
    start_date = datetime(2024, 1, 1),
    schedule = None,
    catchup  = False,
    tags     = ["test", "ssh", "diagnostic"],
) as dag:

    setup_connection = PythonOperator(
        task_id         = "create_ssh_connection",
        python_callable = create_test_connection,
    )

    test_whoami = SSHOperator(
        task_id    = "test_whoami",
        ssh_conn_id = CONN_ID,
        command    = "whoami",
        get_pty    = True,
    )

    test_hostname = SSHOperator(
        task_id    = "test_hostname",
        ssh_conn_id = CONN_ID,
        command    = "hostname && uname -a",
        get_pty    = True,
    )

    test_create_file = SSHOperator(
        task_id    = "test_create_file",
        ssh_conn_id = CONN_ID,
        command    = (
            "touch ~/airflow_test.txt && "
            "echo 'SSH from Airflow worked at $(date)' >> ~/airflow_test.txt && "
            "cat ~/airflow_test.txt"
        ),
        get_pty    = True,
    )

    # --- sudo tests ---
    # Test 1: sudo without password prompt (checks if NOPASSWD is configured)
    test_sudo_nopasswd = SSHOperator(
        task_id     = "test_sudo_nopasswd",
        ssh_conn_id = CONN_ID,
        command     = (
            "sudo -n whoami"
            # -n = non-interactive, fails immediately if password is required
            # If this succeeds → NOPASSWD is configured, sudo will work fine
            # If this fails   → sudo requires a password, which causes SSH timeout
        ),
        get_pty     = True,
    )

    setup_connection >> test_whoami >> test_hostname >> test_create_file
    test_create_file >> test_sudo_nopasswd 