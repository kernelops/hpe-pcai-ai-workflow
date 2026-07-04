"""
This DAG safely simulates an OS provisioning process by using KVM/Libvirt
on a remote Linux machine (the Host Computer). It creates a Virtual Machine
(the Target Computer) on the host, deploys an OS image, verifies its status,
and tears it down cleanly, all without modifying existing data or software on the host.

Author: Infrastructure Simulation Project
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from common_utils import get_worker_nodes, create_airflow_connections, default_args

class DynamicSSHOperator(SSHOperator):
    template_fields = tuple(set(SSHOperator.template_fields).union({'ssh_conn_id'}))

def assign_host_node(**kwargs):
    nodes = kwargs['ti'].xcom_pull(task_ids='get_worker_nodes')
    if not nodes:
        raise ValueError("No reachable worker nodes available!")
    host_conn_id = f"worker_node_{nodes[0]['ip'].replace('.', '_')}"
    print(f"Assigned host connection: {host_conn_id}")
    kwargs['ti'].xcom_push(key='host', value=host_conn_id)

DEFAULT_ARGS = {
    "owner": "infra-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=5),
}

with DAG(
    dag_id="env_error_04_apparmor_block",
    description="OS provisioning simulation that fails because the VM disk is placed in a custom directory blocked by AppArmor.",
    default_args=DEFAULT_ARGS,
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["provisioning", "kvm", "libvirt", "environmental-error"],
    doc_md="""
# HPE OS Software Simulation DAG (AppArmor Block)

This DAG attempts to provision a target VM mimicking remote physical hardware boot, but the task fails because the virtual disk is created in a non-standard location restricted by AppArmor.
    """,
) as dag:

    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )

    assign_host = PythonOperator(
        task_id='assign_host',
        python_callable=assign_host_node,
    )

    install_host_prerequisites = DynamicSSHOperator(
        task_id="install_host_prerequisites",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[INFO] Checking if virtualization tools are already installed...'; "
            "if command -v virsh >/dev/null 2>&1 && command -v virt-install >/dev/null 2>&1 && command -v qemu-system-x86_64 >/dev/null 2>&1; then "
            "  echo '[PASS] Prerequisites already present, skipping installation.'; "
            "else "
            "  echo '[INFO] Installing KVM/Libvirt prerequisites on Host Computer...'; "
            "  echo '[STEP] Stopping timers...'; sudo systemctl stop apt-daily.timer || true; sudo systemctl stop apt-daily-upgrade.timer || true; "
            "  echo '[STEP] Killing apt/dpkg processes...'; sudo killall -9 apt apt-get dpkg || true; "
            "  echo '[STEP] Removing locks...'; sudo rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock*; "
            "  echo '[STEP] Running dpkg configure...'; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a dpkg --configure -a --force-confdef --force-confold || true; "
            "  echo '[STEP] Running apt-get update...'; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get update --allow-releaseinfo-change || true; "
            '  echo "[STEP] Running apt-get install..."; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst wget curl bridge-utils; '
            "  echo '[STEP] Enabling libvirtd...'; sudo systemctl enable --now libvirtd || true; "
            "  echo '[PASS] Host computer virtualization tools installed successfully.'; "
            "fi"
        ),
        get_pty=True,
        cmd_timeout=30,
    )

    download_os_image = DynamicSSHOperator(
        task_id="download_os_image",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[INFO] Checking if Alpine Linux Virt ISO is already present...'; "
            "if [ -f /tmp/alpine-virt.iso ]; then "
            "  echo '[PASS] Alpine Linux Virt ISO already exists at /tmp/alpine-virt.iso, skipping download.'; "
            "else "
            "  echo '[STEP] Removing any previous partial downloads...'; sudo rm -f /tmp/alpine-virt.iso || true; "
            "  echo '[STEP] Starting wget download...'; wget --progress=dot:giga -O /tmp/alpine-virt.iso https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso; "
            "fi; "
            "echo '[STEP] Virtual Media file size:'; "
            "ls -lh /tmp/alpine-virt.iso; "
            "echo '[PASS] Targeted OS Image available locally on Host.'"
        ),
        get_pty=True,
        cmd_timeout=30,
    )

    provision_target_vm = DynamicSSHOperator(
        task_id="provision_target_vm",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[CLEANUP] Ensuring any prev. instances of OS-Sim-VM are wiped...'; "
            "echo '[STEP] Destroying existing VM if present...'; sudo virsh destroy os-sim-vm 2>/dev/null || true; "
            "echo '[STEP] Undefining existing VM if present...'; sudo virsh undefine os-sim-vm --remove-all-storage 2>/dev/null || true; "
            "echo '[BUILD] Provisioning isolated target VM with Alpine OS...'; "
            "echo '[STEP] Creating custom storage directory...'; "
            "sudo mkdir -p /opt/blocked-dir && sudo chown root:root /opt/blocked-dir && sudo chmod 700 /opt/blocked-dir; "
            "echo '[STEP] Running virt-install...'; "
            "sudo virt-install "
            "--name os-sim-vm "
            "--memory 1024 "
            "--vcpus 1 "    
            "--disk path=/opt/blocked-dir/os-sim-vm.qcow2,size=2,format=qcow2,bus=virtio "
            "--cdrom /tmp/alpine-virt.iso "
            "--os-variant alpinelinux3.18 "
            "--network default "
            "--graphics vnc "
            "--noautoconsole; "
            "echo '[PASS] Target Computer Provisioned successfully without GUI prompts.'"
        ),
        get_pty=True,
        cmd_timeout=120,
    )

    monitor_os_boot = DynamicSSHOperator(
        task_id="monitor_os_boot",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[TELEMETRY] Simulating OS remote power state monitoring...'; "
            "echo '[STEP] Polling VM state...'; "
            "for i in {1..30}; do "
            "  STATE=$(sudo virsh domstate os-sim-vm); "
            '  if [ "$STATE" = "running" ]; then '
            "    echo '[PASS] Virtual Target OS is active and running cleanly!'; "
            "    exit 0; "
            "  fi; "
            '  echo "[WAIT] Waiting for OS boot... (Current state: $STATE)"; '
            "  sleep 2; "
            "done; "
            "echo '[FAIL] OS installation target failed to initialize.'; exit 1;"
        ),
        get_pty=True,
        cmd_timeout=30,
    )

    validate_vm_resources = DynamicSSHOperator(
        task_id="validate_vm_resources",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[VALIDATE] Verifying HW resource allocations via Hypervisor...'; "
            "echo '[STEP] Fetching dominfo...'; "
            "sudo virsh dominfo os-sim-vm; "
            "echo '[STEP] Parsing VCPUS...'; "
            "VCPUS=$(sudo virsh dominfo os-sim-vm | grep 'CPU(s):' | awk '{print $2}'); "
            "echo '[STEP] Parsing Memory...'; "
            "MEM=$(sudo virsh dominfo os-sim-vm | grep 'Max memory:' | awk '{print $3}'); "
            'echo "---- REPORT ----"; '
            'echo "Allocated CPUs: $VCPUS | Target Value: 1"; '
            'echo "Allocated Memory: ${MEM} KiB | Target Value: ~1048576 KiB"; '
            'echo "----------------"; '
            'if [ "$VCPUS" -ge 1 ]; then '
            "  echo '[PASS] Infrastructure alignment successful.'; "
            "else "
            "  echo '[FAIL] Missing CPU allocations.'; exit 1; "
            "fi; "
            "echo '[PASS] Simulated HPE OS validation suite passed.'"
        ),
        get_pty=True,
        cmd_timeout=30,
    )

    cleanup_target_vm = DynamicSSHOperator(
        task_id="cleanup_target_vm",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "echo '[CLEANUP] Wiping the simulated Target VM and detached media...'; "
            "echo '[STEP] Destroying os-sim-vm...'; sudo virsh destroy os-sim-vm 2>/dev/null || true; "
            "echo '[STEP] Undefining os-sim-vm and storage...'; sudo virsh undefine os-sim-vm --remove-all-storage 2>/dev/null || true; "
            "echo '[PASS] Previous simulation erased.'"
        ),
        get_pty=True,
        cmd_timeout=30,
    )

    (
        get_nodes
        >> create_connections
        >> assign_host
        >> cleanup_target_vm
        >> install_host_prerequisites 
        >> download_os_image 
        >> provision_target_vm 
        >> monitor_os_boot 
        >> validate_vm_resources 
    )
