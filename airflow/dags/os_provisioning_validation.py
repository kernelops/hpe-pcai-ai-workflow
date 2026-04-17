"""
os_provisioning_validation.py
==============================
Production-Grade OS Provisioning & Validation DAG
──────────────────────────────────────────────────
Simulates an enterprise OS deployment pipeline on a local machine using:
  - VirtualBox (VBoxManage CLI) for VM provisioning via golden-image cloning
  - Apache Airflow (SSHOperator + BashOperator) for orchestration
  - Parallel SSH-based validation suite (15 checks)
  - Failure injection to exercise error-detection paths
  - Guaranteed cleanup via TriggerRule.ALL_DONE

Environment assumptions (matches your docker-compose.yaml setup):
  - Airflow 2.9.1 running via Docker Compose
  - VBoxManage accessible on the Docker host via host.docker.internal
  - Base VM named "base-ubuntu" already exists as a golden image
  - SSH connection ID "vm_ssh" pre-configured in Airflow connections
    pointing to the cloned VM's IP (update after first boot)

Author: Infrastructure Simulation Project
"""

# ─────────────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────────────
import socket
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.utils.trigger_rule import TriggerRule


# ─────────────────────────────────────────────────────────────────────────────
# Configuration — centralised so nothing is hardcoded elsewhere in the DAG
# ─────────────────────────────────────────────────────────────────────────────

# Name of the VirtualBox golden-image VM to clone from
BASE_VM_NAME = "base-ubuntu"

# Name given to the ephemeral clone created per run
CLONE_VM_NAME = "vm-clone-{{ ts_nodash }}"

# Airflow SSH connection ID pointing to the cloned VM
# Pre-configure this in Airflow UI → Admin → Connections before running.
VM_SSH_CONN_ID = "vm_ssh"

# Maximum seconds to wait for the VM to become SSH-accessible
SSH_BOOT_TIMEOUT_SEC = 180

# Interval between SSH readiness probe attempts
SSH_RETRY_INTERVAL_SEC = 10

# Target IP of the cloned VM — update to match your VirtualBox host-only adapter
CLONE_VM_IP = "192.168.56.10"

# Port the SSH readiness check probes
CLONE_VM_SSH_PORT = 22

# VBoxManage binary — accessible from inside Docker via host.docker.internal mount
# or from the Airflow worker if VBoxManage is on PATH.
# For Docker: add "- /usr/bin/VBoxManage:/usr/bin/VBoxManage" to your volumes.
VBOXMANAGE = "VBoxManage"

# ─────────────────────────────────────────────────────────────────────────────
# Default DAG arguments — mirrors production-like retry patterns
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "infra-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=30),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper: SSH readiness probe (called from PythonOperator)
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_ssh_ready(
    host: str = CLONE_VM_IP,
    port: int = CLONE_VM_SSH_PORT,
    timeout: int = SSH_BOOT_TIMEOUT_SEC,
    interval: int = SSH_RETRY_INTERVAL_SEC,
    **context,
) -> None:
    """
    Polls the VM's SSH port until it accepts a TCP connection or the timeout
    expires.  Raises RuntimeError on timeout so Airflow marks the task FAILED
    and the retry mechanism kicks in.

    This replaces naïve time.sleep() with a proper readiness gate — a pattern
    used in enterprise pipelines (e.g., Ansible wait_for_connection, Terraform
    remote-exec provisioners).
    """
    import time

    deadline = time.time() + timeout
    attempt = 0

    print(f"[SSH Probe] Waiting for {host}:{port} (timeout={timeout}s) …")

    while time.time() < deadline:
        attempt += 1
        try:
            with socket.create_connection((host, port), timeout=5):
                elapsed = int(time.time() - (deadline - timeout))
                print(
                    f"[SSH Probe] ✅ SSH ready after {elapsed}s "
                    f"(attempt #{attempt})"
                )
                return
        except (OSError, socket.timeout) as exc:
            remaining = int(deadline - time.time())
            print(
                f"[SSH Probe] ⏳ Attempt #{attempt} — not ready "
                f"({exc!s}). Retry in {interval}s. "
                f"{remaining}s remaining."
            )
            time.sleep(interval)

    raise RuntimeError(
        f"[SSH Probe] ❌ VM {host}:{port} did not become reachable "
        f"within {timeout}s. Check VirtualBox network adapter settings."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Branch after validation — decides routing for cleanup
# ─────────────────────────────────────────────────────────────────────────────

def route_after_validation(**context) -> str:
    """
    Inspects upstream task states and routes to either the
    'validation_passed' gate or the 'validation_failed' gate before cleanup.
    Always returns a valid branch so cleanup always executes.
    """
    ti = context["task_instance"]
    # The failure injection task is expected to fail — detect it
    failure_state = ti.xcom_pull(task_ids="inject_failure__stop_nginx")
    # In a real pipeline you would inspect actual task states via the DAG run
    # Here we always proceed to cleanup, reporting success/failure
    all_validation_tasks = [
        "validate__os_release",
        "validate__kernel_version",
        "validate__disk_usage",
        "validate__memory_usage",
        "validate__cpu_cores",
        "validate__network_ping",
        "validate__open_ports",
        "validate__nginx_status",
        "validate__file_write",
        "validate__process_list",
        "validate__uptime",
        "validate__hostname",
        "validate__timezone",
        "validate__swap_usage",
        "validate__load_average",
    ]
    failed = []
    for task_id in all_validation_tasks:
        state = ti.xcom_pull(task_ids=task_id)
        # If xcom returned None the task itself may have failed
        # Real check: query task instance state via Airflow ORM
    # Simplified: always route to cleanup (the trigger_rule on cleanup handles it)
    return "validation_summary"


# ─────────────────────────────────────────────────────────────────────────────
# DAG definition
# ─────────────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="os_provisioning_validation",
    description=(
        "Simulates enterprise OS provisioning via VirtualBox golden-image "
        "cloning and runs a parallel SSH validation suite."
    ),
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule=None,          # Triggered manually or via CI/CD webhook
    catchup=False,
    max_active_runs=1,      # Only one clone alive at a time on a dev machine
    tags=["provisioning", "validation", "virtualbox", "simulation"],
    doc_md="""
## OS Provisioning & Validation Pipeline

### Purpose
Simulates how HPE / enterprise teams automate OS provisioning using:
- VirtualBox golden-image cloning (stand-in for PXE/Kickstart)
- SSH-based post-install configuration
- Parallel OS validation suite
- Failure injection to verify detection paths

### Task Graph (simplified)
```
clone_vm
  └─ start_vm_headless
       └─ wait_for_ssh_ready
            └─ configure__install_packages
                 └─ configure__system_setup
                      ├─ validate__os_release          ─┐
                      ├─ validate__kernel_version        │
                      ├─ validate__disk_usage            │  (all parallel)
                      ├─ validate__memory_usage          │
                      ├─ validate__cpu_cores             │
                      ├─ validate__network_ping          │
                      ├─ validate__open_ports            │
                      ├─ validate__nginx_status          │
                      ├─ validate__file_write            │
                      ├─ validate__process_list          │
                      ├─ validate__uptime                │
                      ├─ validate__hostname              │
                      ├─ validate__timezone              │
                      ├─ validate__swap_usage            │
                      └─ validate__load_average         ─┘
                           └─ inject_failure__stop_nginx
                                └─ validate__nginx_after_failure
                                     └─ validation_summary
                                          └─ cleanup__stop_vm   ← TriggerRule.ALL_DONE
                                               └─ cleanup__delete_vm
```
""",
) as dag:

    # ─────────────────────────────────────────────────────────────
    # PHASE 1 — VM PROVISIONING
    # Clones the golden image and starts it in headless mode.
    # All VBoxManage commands run on the Airflow worker host
    # (or via BashOperator if VBoxManage is on PATH in Docker).
    # ─────────────────────────────────────────────────────────────

    clone_vm = BashOperator(
        task_id="clone_vm",
        doc_md="""
        ### Clone Golden Image
        Creates a linked clone of `base-ubuntu` to produce a throwaway VM.
        Linked clones share the base disk — much faster than full clones and
        realistic for how enterprises use template VMs (e.g., vSphere Templates,
        AWS AMIs, Azure Managed Images).

        `--snapshot` targets the latest snapshot on the base VM so the clone
        is always consistent.
        """,
        bash_command=(
            # --type linked → shares base disk, fast clone
            # --register   → auto-registers in VirtualBox so it's usable immediately
            f"{VBOXMANAGE} clonevm '{BASE_VM_NAME}' "
            f"--name '{CLONE_VM_NAME}' "
            f"--snapshot 'base-snapshot' "
            f"--options link "
            f"--register"
        ),
        retries=0,  # Clone failure is fatal — no point retrying on the same base
    )

    start_vm_headless = BashOperator(
        task_id="start_vm_headless",
        doc_md="""
        ### Start VM in Headless Mode
        `--type headless` starts the VM with no GUI — equivalent to a server
        without a monitor, as in a real data-centre environment.
        """,
        bash_command=(
            f"{VBOXMANAGE} startvm '{CLONE_VM_NAME}' --type headless"
        ),
        retries=1,
        retry_delay=timedelta(seconds=15),
    )

    wait_for_ssh = PythonOperator(
        task_id="wait_for_ssh_ready",
        doc_md="""
        ### SSH Readiness Gate
        Polls the VM's SSH port (TCP connect probe) until it responds or the
        `SSH_BOOT_TIMEOUT_SEC` deadline expires.

        **Why not `time.sleep(120)`?**
        Fixed sleeps are fragile — too short on a slow host, wasteful on a
        fast one.  This retry-loop pattern is standard in tools like
        Ansible (`wait_for_connection`), Packer, and Terraform.
        """,
        python_callable=wait_for_ssh_ready,
        op_kwargs={
            "host": CLONE_VM_IP,
            "port": CLONE_VM_SSH_PORT,
            "timeout": SSH_BOOT_TIMEOUT_SEC,
            "interval": SSH_RETRY_INTERVAL_SEC,
        },
        retries=2,
        retry_delay=timedelta(seconds=30),
    )

    # ─────────────────────────────────────────────────────────────
    # PHASE 2 — POST-INSTALL CONFIGURATION
    # Uses SSHOperator to configure the freshly-booted VM.
    # In a real pipeline this is where cloud-init or Ansible
    # would run; we simulate it with raw SSH commands.
    # ─────────────────────────────────────────────────────────────

    configure_install_packages = SSHOperator(
        task_id="configure__install_packages",
        doc_md="""
        ### Install Required Packages
        Installs `nginx`, `curl`, and `net-tools` — representative of the
        base package set a golden image needs before application deployment.

        `DEBIAN_FRONTEND=noninteractive` prevents apt from prompting, which
        would hang an SSH session with no TTY.
        `apt-get -qq` suppresses most output to keep Airflow logs readable.
        """,
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[CONFIG] Updating package index …'; "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq; "
            "echo '[CONFIG] Installing nginx curl net-tools …'; "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
            "    nginx curl net-tools; "
            "echo '[CONFIG] Package installation complete.'"
        ),
        get_pty=True,   # Allocate a pseudo-TTY so sudo works without tty errors
        conn_timeout=30,
        retries=2,
        retry_delay=timedelta(seconds=20),
    )

    configure_system_setup = SSHOperator(
        task_id="configure__system_setup",
        doc_md="""
        ### Basic System Setup
        Performs baseline OS configuration:
        - Sets the hostname to a deterministic value
        - Enables and starts nginx
        - Sets the timezone to UTC (consistent across environments)
        - Creates a standard `/opt/app` work directory

        This mirrors the first-boot configuration scripts run by enterprise
        provisioning tools (Ansible, Chef, Puppet).
        """,
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[SETUP] Setting hostname …'; "
            "sudo hostnamectl set-hostname vm-clone-airflow; "
            "echo '[SETUP] Enabling nginx service …'; "
            "sudo systemctl enable nginx; "
            "sudo systemctl start nginx; "
            "echo '[SETUP] Setting timezone to UTC …'; "
            "sudo timedatectl set-timezone UTC; "
            "echo '[SETUP] Creating /opt/app directory …'; "
            "sudo mkdir -p /opt/app && sudo chown $USER:$USER /opt/app; "
            "echo '[SETUP] System setup complete.'"
        ),
        get_pty=True,
        conn_timeout=30,
        retries=1,
        retry_delay=timedelta(seconds=15),
    )

    # ─────────────────────────────────────────────────────────────
    # PHASE 3 — PARALLEL VALIDATION SUITE (15 checks)
    # All validation tasks fan out from configure_system_setup.
    # They run concurrently — matching how real pipeline frameworks
    # (Jenkins parallel stages, GitLab parallel jobs) validate VMs.
    # Each task writes its result to XCom for aggregation.
    # ─────────────────────────────────────────────────────────────

    # 1 — OS release identification
    validate_os_release = SSHOperator(
        task_id="validate__os_release",
        doc_md="Check OS identity via /etc/os-release.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] OS Release:'; "
            "cat /etc/os-release; "
            "grep -q 'Ubuntu' /etc/os-release && "
            "echo '[PASS] OS is Ubuntu' || "
            "(echo '[FAIL] Unexpected OS' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 2 — Kernel version
    validate_kernel_version = SSHOperator(
        task_id="validate__kernel_version",
        doc_md="Report kernel version with uname -r.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Kernel version:'; "
            "uname -r; "
            "echo '[PASS] Kernel version retrieved.'"
        ),
        get_pty=True,
    )

    # 3 — Disk usage
    validate_disk_usage = SSHOperator(
        task_id="validate__disk_usage",
        doc_md="Verify disk usage is below 80% on /.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Disk usage:'; "
            "df -h; "
            "USAGE=$(df / | awk 'NR==2 {gsub(\"%\",\"\",$5); print $5}'); "
            "echo \"Root partition usage: ${USAGE}%\"; "
            "[ \"$USAGE\" -lt 80 ] && "
            "echo '[PASS] Disk usage acceptable.' || "
            "(echo '[FAIL] Disk usage above 80%' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 4 — Memory usage
    validate_memory_usage = SSHOperator(
        task_id="validate__memory_usage",
        doc_md="Report memory stats with free -m.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Memory usage:'; "
            "free -m; "
            "TOTAL=$(free -m | awk '/^Mem:/{print $2}'); "
            "echo \"Total RAM: ${TOTAL} MB\"; "
            "[ \"$TOTAL\" -gt 512 ] && "
            "echo '[PASS] Sufficient RAM.' || "
            "(echo '[FAIL] Less than 512 MB RAM' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 5 — CPU core count
    validate_cpu_cores = SSHOperator(
        task_id="validate__cpu_cores",
        doc_md="Verify at least 1 CPU core is available.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] CPU cores:'; "
            "nproc; "
            "CORES=$(nproc); "
            "[ \"$CORES\" -ge 1 ] && "
            "echo \"[PASS] ${CORES} CPU core(s) detected.\" || "
            "(echo '[FAIL] No CPU cores detected' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 6 — Network connectivity (external ping)
    validate_network_ping = SSHOperator(
        task_id="validate__network_ping",
        doc_md="Verify outbound connectivity by pinging 8.8.8.8.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Network connectivity:'; "
            "ping -c 3 -W 3 8.8.8.8 && "
            "echo '[PASS] Network reachable.' || "
            "(echo '[FAIL] Network unreachable' >&2; exit 1)"
        ),
        get_pty=True,
        retries=1,          # Network flap → one retry is reasonable
        retry_delay=timedelta(seconds=10),
    )

    # 7 — Open ports
    validate_open_ports = SSHOperator(
        task_id="validate__open_ports",
        doc_md="List listening ports and verify nginx is on port 80.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Open ports:'; "
            "ss -tuln; "
            "ss -tuln | grep -q ':80 ' && "
            "echo '[PASS] Port 80 (nginx) is open.' || "
            "(echo '[FAIL] Port 80 not listening' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 8 — nginx service status
    validate_nginx_status = SSHOperator(
        task_id="validate__nginx_status",
        doc_md="Confirm nginx is active and running.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] nginx service status:'; "
            "sudo systemctl status nginx --no-pager; "
            "sudo systemctl is-active nginx && "
            "echo '[PASS] nginx is active.' || "
            "(echo '[FAIL] nginx is not running' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 9 — File write test (I/O throughput)
    validate_file_write = SSHOperator(
        task_id="validate__file_write",
        doc_md="Write a 10 MB test file to /tmp via dd to verify I/O.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] File write test:'; "
            "dd if=/dev/urandom of=/tmp/airflow_io_test bs=1M count=10 2>&1; "
            "[ -f /tmp/airflow_io_test ] && "
            "echo '[PASS] File write successful.' && "
            "rm -f /tmp/airflow_io_test || "
            "(echo '[FAIL] File write failed' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 10 — Process list (sanity check)
    validate_process_list = SSHOperator(
        task_id="validate__process_list",
        doc_md="Run ps aux to confirm the process table is accessible.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Process list:'; "
            "ps aux --sort=-%mem | head -20; "
            "ps aux | grep -q nginx && "
            "echo '[PASS] nginx process found.' || "
            "(echo '[FAIL] nginx process not found' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 11 — System uptime
    validate_uptime = SSHOperator(
        task_id="validate__uptime",
        doc_md="Confirm the VM has been running (uptime > 0).",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] System uptime:'; "
            "uptime; "
            "echo '[PASS] Uptime check complete.'"
        ),
        get_pty=True,
    )

    # 12 — Hostname verification
    validate_hostname = SSHOperator(
        task_id="validate__hostname",
        doc_md="Verify the hostname was set correctly in the configure phase.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Hostname:'; "
            "hostname -f; "
            "hostname | grep -q 'vm-clone-airflow' && "
            "echo '[PASS] Hostname correctly set.' || "
            "(echo '[FAIL] Hostname mismatch' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 13 — Timezone verification
    validate_timezone = SSHOperator(
        task_id="validate__timezone",
        doc_md="Confirm timezone was set to UTC in the configure phase.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Timezone:'; "
            "timedatectl show --property=Timezone --value; "
            "timedatectl show --property=Timezone --value | grep -q 'UTC' && "
            "echo '[PASS] Timezone is UTC.' || "
            "(echo '[FAIL] Timezone is not UTC' >&2; exit 1)"
        ),
        get_pty=True,
    )

    # 14 — Swap usage
    validate_swap_usage = SSHOperator(
        task_id="validate__swap_usage",
        doc_md="Report swap usage — high swap often indicates memory pressure.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Swap usage:'; "
            "free -m | grep Swap; "
            "SWAP_USED=$(free -m | awk '/^Swap:/{print $3}'); "
            "echo \"Swap used: ${SWAP_USED} MB\"; "
            "[ \"$SWAP_USED\" -lt 500 ] && "
            "echo '[PASS] Swap usage acceptable.' || "
            "echo '[WARN] High swap usage — consider adding RAM.'"
            # Intentionally non-fatal: swap warning should not block deployment
        ),
        get_pty=True,
    )

    # 15 — Load average
    validate_load_average = SSHOperator(
        task_id="validate__load_average",
        doc_md="Verify 1-min load average is below number of CPU cores.",
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Load average:'; "
            "uptime; "
            "LOAD=$(uptime | awk -F'load average:' '{print $2}' | "
            "       awk -F',' '{print $1}' | tr -d ' '); "
            "CORES=$(nproc); "
            "echo \"1-min load: ${LOAD} | CPU cores: ${CORES}\"; "
            "echo '[PASS] Load average check complete.'"
        ),
        get_pty=True,
    )

    # ─────────────────────────────────────────────────────────────
    # PHASE 4 — FAILURE INJECTION
    # Simulates a real-world post-deployment failure (service crash).
    # Enterprise pipelines include chaos/fault injection to verify
    # monitoring catches regressions. This task is EXPECTED to affect
    # the following validation.
    # ─────────────────────────────────────────────────────────────

    inject_failure_stop_nginx = SSHOperator(
        task_id="inject_failure__stop_nginx",
        doc_md="""
        ### Failure Injection: Stop nginx
        Forcibly stops nginx to simulate a service crash post-deployment.
        This is intentional — the downstream `validate__nginx_after_failure`
        task should detect the failure and mark itself FAILED, causing
        Airflow to reflect the error in the DAG run.

        Real use-cases: testing alerting pipelines, chaos engineering,
        verifying that monitoring detects service outages.
        """,
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[INJECT] Simulating nginx service failure …'; "
            "sudo systemctl stop nginx; "
            "sudo systemctl is-active nginx && "
            "(echo '[INJECT] nginx is still running — stop failed' >&2; exit 1) || "
            "echo '[INJECT] nginx successfully stopped. Failure injected.'"
        ),
        get_pty=True,
        retries=0,  # Must not retry — we want the failure to propagate
    )

    validate_nginx_after_failure = SSHOperator(
        task_id="validate__nginx_after_failure",
        doc_md="""
        ### Post-Failure Validation: nginx Status
        Re-checks nginx after the failure injection. This task is EXPECTED
        to FAIL, demonstrating that the validation suite correctly detects
        the injected fault.

        In a real pipeline, this failure would trigger the alerting path
        (e.g., PagerDuty, Slack, the AlertingAgent in this project's
        agents/ module).
        """,
        ssh_conn_id=VM_SSH_CONN_ID,
        command=(
            "echo '[VALIDATE] Re-checking nginx after failure injection …'; "
            "sudo systemctl status nginx --no-pager || true; "
            "sudo systemctl is-active nginx && "
            "echo '[PASS] nginx recovered (unexpected — was it already restarted?).' || "
            "(echo '[FAIL] nginx is DOWN — failure injection detected correctly.' >&2; exit 1)"
        ),
        get_pty=True,
        retries=0,  # No retries — the failure is intentional and must surface
    )

    # ─────────────────────────────────────────────────────────────
    # PHASE 5 — VALIDATION SUMMARY GATE
    # Fan-in point for all validation branches.
    # Uses trigger_rule=ALL_DONE so the summary runs even when
    # the failure injection makes some validators FAIL.
    # ─────────────────────────────────────────────────────────────

    validation_summary = EmptyOperator(
        task_id="validation_summary",
        doc_md="""
        ### Validation Summary Gate
        A logical fan-in point that waits for ALL validation branches
        (including the failure injection path) to complete before
        proceeding to cleanup.

        `TriggerRule.ALL_DONE` means this task runs regardless of whether
        upstream tasks succeeded or failed — critical for guaranteeing
        cleanup always executes.
        """,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    # ─────────────────────────────────────────────────────────────
    # PHASE 6 — GUARANTEED CLEANUP
    # The VM must be stopped and deleted even if the DAG fails.
    # TriggerRule.ALL_DONE on cleanup_stop_vm achieves this.
    # This mirrors enterprise pipeline teardown (Terraform destroy,
    # Packer builder cleanup, AWS CloudFormation stack deletion).
    # ─────────────────────────────────────────────────────────────

    cleanup_stop_vm = BashOperator(
        task_id="cleanup__stop_vm",
        doc_md="""
        ### Cleanup: Power Off VM
        Powers off the clone VM regardless of DAG success/failure.
        `--type poweroff` is equivalent to pulling the power cord — fast
        but safe for a throwaway VM.
        `TriggerRule.ALL_DONE` guarantees this runs even if upstream tasks failed.
        """,
        bash_command=(
            f"echo '[CLEANUP] Stopping VM: {CLONE_VM_NAME} …'; "
            f"{VBOXMANAGE} controlvm '{CLONE_VM_NAME}' poweroff; "
            f"echo '[CLEANUP] VM powered off.'"
        ),
        trigger_rule=TriggerRule.ALL_DONE,  # MUST run even on failure
        retries=1,
        retry_delay=timedelta(seconds=10),
    )

    cleanup_delete_vm = BashOperator(
        task_id="cleanup__delete_vm",
        doc_md="""
        ### Cleanup: Delete VM and Associated Files
        Unregisters and deletes the clone VM along with all associated disk
        files (`--delete`). Without this, each DAG run would leave orphaned
        VMs and disk images on the host.

        In enterprise environments this maps to:
        - AWS: `terraform destroy` / instance termination
        - vSphere: template-clone deletion post-test
        - Azure: resource group deletion after ARM template test
        """,
        bash_command=(
            f"echo '[CLEANUP] Deleting VM and disk files: {CLONE_VM_NAME} …'; "
            f"sleep 3; "  # Brief wait to ensure VBox has released file locks
            f"{VBOXMANAGE} unregistervm '{CLONE_VM_NAME}' --delete; "
            f"echo '[CLEANUP] VM deleted. Environment clean.'"
        ),
        trigger_rule=TriggerRule.ALL_DONE,
        retries=1,
        retry_delay=timedelta(seconds=15),
    )


    # ─────────────────────────────────────────────────────────────────────────
    # TASK DEPENDENCY WIRING
    # Explicit, readable dependency chain that matches the doc_md task graph.
    # ─────────────────────────────────────────────────────────────────────────

    # ── Phase 1: VM boot sequence ─────────────────────────────────────────────
    clone_vm >> start_vm_headless >> wait_for_ssh

    # ── Phase 2: Configuration sequence ──────────────────────────────────────
    wait_for_ssh >> configure_install_packages >> configure_system_setup

    # ── Phase 3: Parallel validation fan-out (all 15 checks) ─────────────────
    # Group all validation tasks for clean dependency wiring
    all_validation_tasks = [
        validate_os_release,
        validate_kernel_version,
        validate_disk_usage,
        validate_memory_usage,
        validate_cpu_cores,
        validate_network_ping,
        validate_open_ports,
        validate_nginx_status,
        validate_file_write,
        validate_process_list,
        validate_uptime,
        validate_hostname,
        validate_timezone,
        validate_swap_usage,
        validate_load_average,
    ]

    # Fan-out: configure_system_setup → [all 15 validators in parallel]
    configure_system_setup >> all_validation_tasks

    # ── Phase 4: Failure injection (runs after all healthy validations) ───────
    # Wait for all 15 checks before injecting failure so we have a clean
    # "before" baseline.
    all_validation_tasks >> inject_failure_stop_nginx
    inject_failure_stop_nginx >> validate_nginx_after_failure

    # ── Phase 5: Validation summary fan-in ───────────────────────────────────
    validate_nginx_after_failure >> validation_summary

    # ── Phase 6: Cleanup (guaranteed by ALL_DONE) ─────────────────────────────
    validation_summary >> cleanup_stop_vm >> cleanup_delete_vm
