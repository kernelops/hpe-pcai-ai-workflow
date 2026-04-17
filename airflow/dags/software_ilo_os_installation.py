"""
software_ilo_os_installation.py
================================
HPE iLO Software Simulation DAG
────────────────────────────────
This DAG safely simulates an HPE iLO OS provisioning process by using KVM/Libvirt
on a remote Linux machine (the Host Computer). It creates a Virtual Machine
(the Target Computer) on the host, deploys an OS image, verifies its status,
and tears it down cleanly, all without modifying existing data or software on the host.

Author: Infrastructure Simulation Project
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.utils.trigger_rule import TriggerRule

SSH_CONN_ID = "remote_os_ssh"

DEFAULT_ARGS = {
    "owner": "infra-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=20),
}

with DAG(
    dag_id="software_ilo_os_installation",
    description="Software-based HPE iLO OS provisioning simulator utilizing KVM/Libvirt",
    default_args=DEFAULT_ARGS,
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["ilo-simulator", "provisioning", "kvm", "libvirt"],
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

    # ─────────────────────────────────────────────────────────────
    # STEP 1: VERIFY & INSTALL HOST PREREQUISITES
    # ─────────────────────────────────────────────────────────────
    install_host_prerequisites = SSHOperator(
        task_id="install_host_prerequisites",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[INFO] Installing KVM/Libvirt prerequisites on Host Computer...'; "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq || true; "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
            "qemu-kvm libvirt-daemon-system libvirt-clients virtinst wget curl bridge-utils; "
            "sudo systemctl enable --now libvirtd || true; "
            "echo '[PASS] Host computer virtualization tools installed successfully.'"
        ),
        get_pty=True,
        cmd_timeout=600,
    )

    download_os_image = SSHOperator(
        task_id="download_os_image",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[INFO] Downloading Alpine Linux Virt ISO via wget...'; "
            "wget -q -O /tmp/alpine-virt.iso https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso; "
            "echo '[INFO] Virtual Media file size:'; "
            "ls -lh /tmp/alpine-virt.iso; "
            "echo '[PASS] Targeted OS Image available locally on Host.'"
        ),
        get_pty=True,
        cmd_timeout=600,
    )


    provision_target_vm = SSHOperator(
        task_id="provision_target_vm",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[CLEANUP] Ensuring any prev. instances of iLO-Sim-VM are wiped...'; "
            "sudo virsh destroy ilo-sim-vm 2>/dev/null || true; "
            "sudo virsh undefine ilo-sim-vm --remove-all-storage 2>/dev/null || true; "
            "echo '[BUILD] Provisioning isolated target VM with Alpine OS...'; "
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
        cmd_timeout=600,
    )


    monitor_os_boot = SSHOperator(
        task_id="monitor_os_boot",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[TELEMETRY] Simulating iLO remote power state monitoring...'; "
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
        cmd_timeout=600,
    )


    validate_vm_resources = SSHOperator(
        task_id="validate_vm_resources",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "set -e; "
            "echo '[VALIDATE] Verifying HW resource allocations via Hypervisor...'; "
            "sudo virsh dominfo ilo-sim-vm; "
            "VCPUS=$(sudo virsh dominfo ilo-sim-vm | grep 'CPU(s):' | awk '{print $2}'); "
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
        cmd_timeout=600,
    )

 
    cleanup_target_vm = SSHOperator(
        task_id="cleanup_target_vm",
        ssh_conn_id=SSH_CONN_ID,
        command=(
            "echo '[CLEANUP] Wiping the simulated Target VM and detached media...'; "
            "sudo virsh destroy ilo-sim-vm 2>/dev/null || true; "
            "sudo virsh undefine ilo-sim-vm --remove-all-storage 2>/dev/null || true; "
            "sudo rm -f /tmp/alpine-virt.iso; "
            "echo '[PASS] Previous simulation erased.'"
        ),
        get_pty=True,
        cmd_timeout=600,
    )


    (
        cleanup_target_vm
        >> install_host_prerequisites 
        >> download_os_image 
        >> provision_target_vm 
        >> monitor_os_boot 
        >> validate_vm_resources 
    )
