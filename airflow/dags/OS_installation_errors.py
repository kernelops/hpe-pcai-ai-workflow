"""
ilo_os_installation_errors.py
================================
HPE Software Simulation DAGs - Error Scenarios
────────────────────────────────
This file dynamically generates 10 different Airflow DAGs,
each simulating a specific failure scenario in the HPE OS provisioning process.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.operators.python import PythonOperator

from common_utils import create_airflow_connections, default_args

def get_worker_nodes(**context):
    dag_run = context.get("dag_run")
    dag_conf = dag_run.conf or {} if dag_run else {}
    conf_nodes = dag_conf.get("worker_nodes") or []
    if conf_nodes:
        return [n for n in conf_nodes if n.get("ip") and n.get("username")]
    return [{"ip": "192.168.0.27", "username": "tejasvi", "password": "Tyagli1234", "status": "reachable"}]

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
    "execution_timeout": timedelta(minutes=20),
}

def create_error_dag(dag_id, failing_task, custom_command, description):
    dag = DAG(
        dag_id=dag_id,
        description=description,
        default_args=DEFAULT_ARGS,
        schedule_interval=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        max_active_runs=1,
        tags=["ilo-simulator", "error-scenario"],
    )

    with dag:
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

        # Baseline commands (success conditions)
        commands = {
            "cleanup_target_vm": (
                "echo '[CLEANUP] Wiping the simulated Target VM and detached media...'; "
                "sudo virsh destroy ilo-sim-vm 2>/dev/null || true; "
                "sudo virsh undefine ilo-sim-vm --remove-all-storage 2>/dev/null || true; "
                "sudo rm -f /tmp/alpine-virt.iso; "
                "echo '[PASS] Previous simulation erased.'"
            ),
            "install_host_prerequisites": (
                "set -e; "
                "echo '[INFO] Installing KVM/Libvirt prerequisites on Host Computer...'; "
                "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq || true; "
                "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
                "qemu-kvm libvirt-daemon-system libvirt-clients virtinst wget curl bridge-utils; "
                "sudo systemctl enable --now libvirtd || true; "
                "echo '[PASS] Host computer virtualization tools installed successfully.'"
            ),
            "download_os_image": (
                "set -e; "
                "echo '[INFO] Downloading Alpine Linux Virt ISO via wget...'; "
                "wget -q -O /tmp/alpine-virt.iso https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso; "
                "echo '[INFO] Virtual Media file size:'; "
                "ls -lh /tmp/alpine-virt.iso; "
                "echo '[PASS] Targeted OS Image available locally on Host.'"
            ),
            "provision_target_vm": (
                "set -e; "
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
            "monitor_os_boot": (
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
            "validate_vm_resources": (
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
            )
        }

        # Override the targeted task with an error-producing command
        commands[failing_task] = custom_command

        # Create tasks
        task_objects = {}
        for task_id, cmd in commands.items():
            task_objects[task_id] = DynamicSSHOperator(
                task_id=task_id,
                ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_host', key='host') }}",
                command=cmd,
                get_pty=True,
                cmd_timeout=600,
            )

        (
            get_nodes
            >> create_connections
            >> assign_host
            >> task_objects["cleanup_target_vm"]
            >> task_objects["install_host_prerequisites"]
            >> task_objects["download_os_image"]
            >> task_objects["provision_target_vm"]
            >> task_objects["monitor_os_boot"]
            >> task_objects["validate_vm_resources"]
        )

    return dag

error_scenarios = [
    {
        "dag_id": "OS_error_01_cleanup_failure",
        "task": "cleanup_target_vm",
        "description": "Simulates failure during cleanup by running a command that is guaranteed to fail.",
        "command": "set -e; echo '[CLEANUP] Attempting to destroy non-existent VM without failure mitigation...'; sudo virsh destroy definitely-does-not-exist-vm-123"
    },
    {
        "dag_id": "OS_error_02_pkg_install_fail",
        "task": "install_host_prerequisites",
        "description": "Simulates failure during package installation by requesting a non-existent package.",
        "command": "set -e; echo '[INFO] Installing non-existent package...'; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq non_pkg_123"
    },
    {
        "dag_id": "OS_error_03_iso_download_404",
        "task": "download_os_image",
        "description": "Simulates wget failing due to a 404 Not Found error (invalid URL).",
        "command": "set -e; echo '[INFO] Downloading from invalid URL...'; wget -q -O /tmp/alpine-virt.iso https://dl-cdn.alpinelinux.org/invalid_path/alpine.iso"
    },
    {
        "dag_id": "OS_error_04_iso_permission_denied",
        "task": "download_os_image",
        "description": "Simulates failure to write ISO due to permission denied.",
        "command": "set -e; echo '[INFO] Attempting to write to protected directory...'; wget -q -O /root/alpine-virt.iso https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso"
    },
    {
        "dag_id": "OS_error_05_virt_install_invalid_arg",
        "task": "provision_target_vm",
        "description": "Simulates failure during provisioning due to invalid memory argument.",
        "command": "set -e; echo '[BUILD] Provisioning with invalid memory...'; sudo virt-install --name ilo-sim-vm --memory 999999999 --vcpus 1 --disk size=2,format=qcow2,bus=virtio --cdrom /tmp/alpine-virt.iso --os-variant alpinelinux3.18 --network default --graphics vnc --noautoconsole"
    },
    {
        "dag_id": "OS_error_06_virt_install_missing_iso",
        "task": "provision_target_vm",
        "description": "Simulates virt-install failing because the specified CDROM iso does not exist.",
        "command": "set -e; echo '[BUILD] Provisioning with missing ISO...'; sudo virt-install --name ilo-sim-vm --memory 1024 --vcpus 1 --disk size=2,format=qcow2,bus=virtio --cdrom /tmp/missing-alpine-virt.iso --os-variant alpinelinux3.18 --network default --graphics vnc --noautoconsole"
    },
    {
        "dag_id": "OS_error_07_monitor_boot_timeout",
        "task": "monitor_os_boot",
        "description": "Simulates timeout waiting for OS to boot by checking for an impossible state.",
        "command": "set -e; echo '[TELEMETRY] Simulating timeout...'; for i in {1..2}; do STATE=$(sudo virsh domstate ilo-sim-vm); echo \"Current state: $STATE\"; sleep 1; done; echo '[FAIL] Timeout waiting for OS boot.'; exit 1;"
    },
    {
        "dag_id": "OS_error_08_monitor_wrong_vm_name",
        "task": "monitor_os_boot",
        "description": "Simulates domstate check failure due to typo in VM name.",
        "command": "set -e; echo '[TELEMETRY] Checking domstate of wrong VM name...'; sudo virsh domstate wrong-vm-name-ilo-sim"
    },
    {
        "dag_id": "OS_error_09_validate_cpu_mismatch",
        "task": "validate_vm_resources",
        "description": "Simulates validation failure by expecting more CPUs than allocated.",
        "command": "set -e; echo '[VALIDATE] Expecting 4 CPUs...'; VCPUS=$(sudo virsh dominfo ilo-sim-vm | grep 'CPU(s):' | awk '{print $2}'); if [ \"$VCPUS\" -ge 4 ]; then echo '[PASS]'; else echo '[FAIL] Expected 4 CPUs, found '$VCPUS; exit 1; fi"
    },
    {
        "dag_id": "OS_error_10_validate_mem_mismatch",
        "task": "validate_vm_resources",
        "description": "Simulates validation failure by enforcing a strict mismatch in memory expectations.",
        "command": "set -e; echo '[VALIDATE] Expecting impossible memory...'; MEM=$(sudo virsh dominfo ilo-sim-vm | grep 'Max memory:' | awk '{print $3}'); if [ \"$MEM\" -eq 9999999 ]; then echo '[PASS]'; else echo '[FAIL] Memory mismatch: expected 9999999, found '$MEM; exit 1; fi"
    }
]

for scenario in error_scenarios:
    globals()[scenario['dag_id']] = create_error_dag(
        scenario['dag_id'],
        scenario['task'],
        scenario['command'],
        scenario['description']
    )
