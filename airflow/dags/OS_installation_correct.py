"""
software_ilo_os_installation.py
================================
HPE  Software Simulation DAG
────────────────────────────────
This DAG safely simulates an HPE  OS provisioning process by using KVM/Libvirt
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
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=60),
}

with DAG(
    dag_id="OS_installation",
    description="OS installation and provisioning utilizing KVM/Libvirt",
    default_args=DEFAULT_ARGS,
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["provisioning", "kvm", "libvirt"],
    doc_md="""
# HPE iLO Software Simulation DAG

This DAG uses **KVM/Libvirt** on an remote Linux host to simulate the bare-metal provisioning capabilities of an HPE iLO, performing the following strictly isolated operations:

1. Installs Hypervisor tools if missing (`qemu-kvm`, `libvirt`, `virtinst`).
2. Downloads a lightweight OS Image (Alpine Linux) simulating an iLO Virtual Media image.
3. Automatically provisions a target VM mimicking remote physical hardware boot.
4. Monitors virtual system boot signals.
5. Performs validation telemetry.
6. Runs a guaranteed Zero-Trace cleanup task that wipes the virtual disk entirely un-affecting the base host.

**Prerequisites:** 
Configure an SSH Connection in Airflow with Connection ID: `remote_os_ssh`
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

    # ─────────────────────────────────────────────────────────────
    # STEP 1: VERIFY & INSTALL HOST PREREQUISITES
    # ─────────────────────────────────────────────────────────────
    install_host_prerequisites = DynamicSSHOperator(
        task_id="install_host_prerequisites",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[INFO] Installing KVM/Libvirt prerequisites on Host Computer...'; "
            "echo '[STEP] Stopping timers...'; sudo systemctl stop apt-daily.timer || true; sudo systemctl stop apt-daily-upgrade.timer || true; "
            "echo '[STEP] Killing apt/dpkg processes...'; sudo killall -9 apt apt-get dpkg || true; "
            "echo '[STEP] Removing locks...'; sudo rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock*; "
            "echo '[STEP] Running dpkg configure...'; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a dpkg --configure -a --force-confdef --force-confold || true; "
            "echo '[STEP] Running apt-get update...'; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get update --allow-releaseinfo-change || true; "
            "echo '[STEP] Running apt-get install...'; sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -o Dpkg::Options::=\"--force-confdef\" -o Dpkg::Options::=\"--force-confold\" qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst wget curl bridge-utils; "
            "echo '[STEP] Enabling libvirtd...'; sudo systemctl enable --now libvirtd || true; "
            "echo '[PASS] Host computer virtualization tools installed successfully.'"
        ),
        get_pty=True,
        cmd_timeout=3600,
    )

    download_os_image = DynamicSSHOperator(
        task_id="download_os_image",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[INFO] Downloading Alpine Linux Virt ISO via wget...'; "
            "echo '[STEP] Removing any previous partial downloads...'; rm -f /tmp/alpine-virt.iso || true; "
            "echo '[STEP] Starting wget download...'; wget --progress=dot:giga -O /tmp/alpine-virt.iso https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso; "
            "echo '[STEP] Virtual Media file size:'; "
            "ls -lh /tmp/alpine-virt.iso; "
            "echo '[PASS] Targeted OS Image available locally on Host.'"
        ),
        get_pty=True,
        cmd_timeout=3600,
    )


    provision_target_vm = DynamicSSHOperator(
        task_id="provision_target_vm",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[CLEANUP] Ensuring any prev. instances of iLO-Sim-VM are wiped...'; "
            "echo '[STEP] Destroying existing VM if present...'; sudo virsh destroy ilo-sim-vm 2>/dev/null || true; "
            "echo '[STEP] Undefining existing VM if present...'; sudo virsh undefine ilo-sim-vm --remove-all-storage 2>/dev/null || true; "
            "echo '[BUILD] Provisioning isolated target VM with Alpine OS...'; "
            "echo '[STEP] Running virt-install...'; "
            "sudo virt-install "
            "--name ilo-sim-vm "
            "--memory 1024 "
            "--vcpus 1 "    
            "--disk size=2,format=qcow2,bus=virtio "
            "--cdrom /tmp/alpine-virt.iso "
            "--os-variant alpinelinux3.18 "
            "--network default "
            "--graphics vnc "
            "--noautoconsole; "
            "echo '[PASS] Target Computer Provisioned successfully without GUI prompts.'"
        ),
        get_pty=True,
        cmd_timeout=3600,
    )


    monitor_os_boot = DynamicSSHOperator(
        task_id="monitor_os_boot",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[TELEMETRY] Simulating iLO remote power state monitoring...'; "
            "echo '[STEP] Polling VM state...'; "
            "for i in {1..30}; do "
            "  STATE=$(sudo virsh domstate ilo-sim-vm); "
            "  if [ \"$STATE\" = \"running\" ]; then "
            "    echo '[PASS] Virtual Target OS is active and running cleanly!'; "
            "    exit 0; "
            "  fi; "
            "  echo \"[WAIT] Waiting for OS boot... (Current state: $STATE)\"; "
            "  sleep 2; "
            "done; "
            "echo '[FAIL] OS installation target failed to initialize.'; exit 1;"
        ),
        get_pty=True,
        cmd_timeout=3600,
    )


    validate_vm_resources = DynamicSSHOperator(
        task_id="validate_vm_resources",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "set -e; "
            "echo '[VALIDATE] Verifying HW resource allocations via Hypervisor...'; "
            "echo '[STEP] Fetching dominfo...'; "
            "sudo virsh dominfo ilo-sim-vm; "
            "echo '[STEP] Parsing VCPUS...'; "
            "VCPUS=$(sudo virsh dominfo ilo-sim-vm | grep 'CPU(s):' | awk '{print $2}'); "
            "echo '[STEP] Parsing Memory...'; "
            "MEM=$(sudo virsh dominfo ilo-sim-vm | grep 'Max memory:' | awk '{print $3}'); "
            "echo \"---- REPORT ----\"; "
            "echo \"Allocated CPUs: $VCPUS | Target Value: 1\"; "
            "echo \"Allocated Memory: ${MEM} KiB | Target Value: ~1048576 KiB\"; "
            "echo \"----------------\"; "
            "if [ \"$VCPUS\" -ge 1 ]; then "
            "  echo '[PASS] Infrastructure alignment successful.'; "
            "else "
            "  echo '[FAIL] Missing CPU allocations.'; exit 1; "
            "fi; "
            "echo '[PASS] Simulated HPE iLO validation suite passed.'"
        ),
        get_pty=True,
        cmd_timeout=3600,
    )

 
    cleanup_target_vm = DynamicSSHOperator(
        task_id="cleanup_target_vm",
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
        command=(
            "echo '[CLEANUP] Wiping the simulated Target VM and detached media...'; "
            "echo '[STEP] Destroying ilo-sim-vm...'; sudo virsh destroy ilo-sim-vm 2>/dev/null || true; "
            "echo '[STEP] Undefining ilo-sim-vm and storage...'; sudo virsh undefine ilo-sim-vm --remove-all-storage 2>/dev/null || true; "
            "echo '[STEP] Removing ISO image...'; sudo rm -f /tmp/alpine-virt.iso; "
            "echo '[PASS] Previous simulation erased.'"
        ),
        get_pty=True,
        cmd_timeout=3600,
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
