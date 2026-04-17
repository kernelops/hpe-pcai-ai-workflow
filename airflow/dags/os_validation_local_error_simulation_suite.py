"""
Suite of error-injected DAGs for local OS validation.
Each DAG mirrors os_validation_local_dag and injects one distinct failure mode.
"""

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
}

VALIDATION_TASK_IDS = [
    "system_checks.check_os_version",
    "system_checks.check_kernel",
    "system_checks.check_cpu_load",
    "system_checks.check_memory",
    "storage_checks.check_disk",
    "storage_checks.check_inode",
    "storage_checks.check_mounts",
    "storage_checks.check_nfs",
    "network_checks.check_connectivity",
    "network_checks.check_dns",
    "network_checks.check_ports",
    "service_checks.check_docker",
    "service_checks.check_ssh",
    "service_checks.check_processes",
    "service_checks.check_failed_services",
    "integration_checks.check_minio_health",
    "integration_checks.check_nfs_write",
]


def aggregate_validation_results(**context):
    """
    Aggregates success/failure across all validation tasks and fails intentionally when any check fails.
    """
    dag_run = context["dag_run"]
    task_instance = context["ti"]

    successful_tasks = []
    failed_tasks = []
    task_outputs = {}

    for task_id in VALIDATION_TASK_IDS:
        current_ti = dag_run.get_task_instance(task_id)
        state = current_ti.state if current_ti else "not_found"
        output = task_instance.xcom_pull(task_ids=task_id)

        task_outputs[task_id] = {
            "state": state,
            "output": output,
        }

        if state == "success":
            successful_tasks.append(task_id)
        else:
            failed_tasks.append(task_id)

    summary_payload = {
        "dag_id": dag_run.dag_id,
        "run_id": dag_run.run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "successful_tasks": successful_tasks,
        "failed_tasks": failed_tasks,
        "task_outputs": task_outputs,
        "summary": "OS validation completed",
    }

    print("Validation aggregation summary:")
    print(json.dumps(summary_payload, indent=2, default=str))

    task_instance.xcom_push(key="validation_summary", value=summary_payload)

    if failed_tasks:
        raise AirflowException("One or more OS validation checks failed.")


def failure_handler_fn(**context):
    """
    Emits structured failure JSON for simulated downstream RAG ingestion.
    """
    dag_run = context["dag_run"]
    task_instance = context["ti"]

    aggregate_payload = task_instance.xcom_pull(
        task_ids="aggregate_results",
        key="validation_summary",
    )

    if aggregate_payload:
        failed_tasks = aggregate_payload.get("failed_tasks", [])
        successful_tasks = aggregate_payload.get("successful_tasks", [])
    else:
        failed_tasks = []
        successful_tasks = []
        for task_id in VALIDATION_TASK_IDS:
            current_ti = dag_run.get_task_instance(task_id)
            if current_ti and current_ti.state == "success":
                successful_tasks.append(task_id)
            else:
                failed_tasks.append(task_id)

    failure_payload = {
        "failed_tasks": failed_tasks,
        "successful_tasks": successful_tasks,
        "dag_id": dag_run.dag_id,
        "timestamp": datetime.utcnow().isoformat(),
        "summary": "OS validation failed",
    }

    print("Failure handler payload (RAG ingestion simulation):")
    print(json.dumps(failure_payload, indent=2, default=str))


def build_error_injected_dag(dag_id: str, description: str, inject_task: str, injected_command: str) -> DAG:
    """
    Build one local OS validation DAG and inject exactly one task command failure.
    """

    # -------------------------
    # System checks commands
    # -------------------------
    check_os_version_cmd = injected_command if inject_task == "check_os_version" else "lsb_release -a"
    check_kernel_cmd = injected_command if inject_task == "check_kernel" else "uname -r && uptime"
    check_cpu_load_cmd = injected_command if inject_task == "check_cpu_load" else "top -bn1 | grep load"
    check_memory_cmd = injected_command if inject_task == "check_memory" else "free -m"

    # --------------------------
    # Storage checks commands
    # --------------------------
    check_disk_cmd = injected_command if inject_task == "check_disk" else "df -h"
    check_inode_cmd = injected_command if inject_task == "check_inode" else "df -i"
    check_mounts_cmd = injected_command if inject_task == "check_mounts" else "mount"
    check_nfs_cmd = injected_command if inject_task == "check_nfs" else "mount | grep nfs || echo 'No NFS mount found'"

    # --------------------------
    # Network checks commands
    # --------------------------
    check_connectivity_cmd = injected_command if inject_task == "check_connectivity" else "ping -c 2 8.8.8.8"
    check_dns_cmd = injected_command if inject_task == "check_dns" else "ping -c 2 google.com"
    check_ports_cmd = injected_command if inject_task == "check_ports" else "ss -tuln | grep -E '22|9000|9001' || echo 'Ports not found'"

    # --------------------------
    # Service checks commands
    # --------------------------
    check_docker_cmd = injected_command if inject_task == "check_docker" else "systemctl is-active docker || echo 'Docker not running'"
    check_ssh_cmd = injected_command if inject_task == "check_ssh" else "systemctl is-active ssh"
    check_processes_cmd = injected_command if inject_task == "check_processes" else "ps aux | grep minio || echo 'MinIO not running'"
    check_failed_services_cmd = injected_command if inject_task == "check_failed_services" else "systemctl --failed || echo 'No failed services'"

    # --------------------------------
    # Integration checks commands
    # --------------------------------
    check_minio_health_cmd = (
        injected_command
        if inject_task == "check_minio_health"
        else "curl -f http://localhost:9000/minio/health/live || echo 'MinIO not reachable'"
    )
    check_nfs_write_cmd = injected_command if inject_task == "check_nfs_write" else "touch /tmp/testfile && rm /tmp/testfile"

    with DAG(
        dag_id=dag_id,
        default_args=default_args,
        description=description,
        schedule_interval=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["local", "validation", "os", "ubuntu", "error-injected"],
    ) as dag:
        start = EmptyOperator(task_id="start")

        with TaskGroup(group_id="system_checks") as system_checks:
            check_os_version = BashOperator(
                task_id="check_os_version",
                bash_command=check_os_version_cmd,
                do_xcom_push=True,
            )
            check_kernel = BashOperator(
                task_id="check_kernel",
                bash_command=check_kernel_cmd,
                do_xcom_push=True,
            )
            check_cpu_load = BashOperator(
                task_id="check_cpu_load",
                bash_command=check_cpu_load_cmd,
                do_xcom_push=True,
            )
            check_memory = BashOperator(
                task_id="check_memory",
                bash_command=check_memory_cmd,
                do_xcom_push=True,
            )

        with TaskGroup(group_id="storage_checks") as storage_checks:
            check_disk = BashOperator(
                task_id="check_disk",
                bash_command=check_disk_cmd,
                do_xcom_push=True,
            )
            check_inode = BashOperator(
                task_id="check_inode",
                bash_command=check_inode_cmd,
                do_xcom_push=True,
            )
            check_mounts = BashOperator(
                task_id="check_mounts",
                bash_command=check_mounts_cmd,
                do_xcom_push=True,
            )
            check_nfs = BashOperator(
                task_id="check_nfs",
                bash_command=check_nfs_cmd,
                do_xcom_push=True,
            )

        with TaskGroup(group_id="network_checks") as network_checks:
            check_connectivity = BashOperator(
                task_id="check_connectivity",
                bash_command=check_connectivity_cmd,
                do_xcom_push=True,
            )
            check_dns = BashOperator(
                task_id="check_dns",
                bash_command=check_dns_cmd,
                do_xcom_push=True,
            )
            check_ports = BashOperator(
                task_id="check_ports",
                bash_command=check_ports_cmd,
                do_xcom_push=True,
            )

        with TaskGroup(group_id="service_checks") as service_checks:
            check_docker = BashOperator(
                task_id="check_docker",
                bash_command=check_docker_cmd,
                do_xcom_push=True,
            )
            check_ssh = BashOperator(
                task_id="check_ssh",
                bash_command=check_ssh_cmd,
                do_xcom_push=True,
            )
            check_processes = BashOperator(
                task_id="check_processes",
                bash_command=check_processes_cmd,
                do_xcom_push=True,
            )
            check_failed_services = BashOperator(
                task_id="check_failed_services",
                bash_command=check_failed_services_cmd,
                do_xcom_push=True,
            )

        with TaskGroup(group_id="integration_checks") as integration_checks:
            check_minio_health = BashOperator(
                task_id="check_minio_health",
                bash_command=check_minio_health_cmd,
                do_xcom_push=True,
            )
            check_nfs_write = BashOperator(
                task_id="check_nfs_write",
                bash_command=check_nfs_write_cmd,
                do_xcom_push=True,
            )

        aggregate_results = PythonOperator(
            task_id="aggregate_results",
            python_callable=aggregate_validation_results,
            trigger_rule=TriggerRule.ALL_DONE,
        )

        failure_handler = PythonOperator(
            task_id="failure_handler",
            python_callable=failure_handler_fn,
            trigger_rule=TriggerRule.ONE_FAILED,
        )

        start >> [system_checks, storage_checks, network_checks, service_checks]
        [system_checks, storage_checks, network_checks, service_checks] >> integration_checks
        integration_checks >> aggregate_results >> failure_handler

    return dag


ERROR_SCENARIOS = [
    (
        "os_validation_local_error_sim_bad_lsb_release",
        "Simulate OS version check failure with invalid binary",
        "check_os_version",
        "lsb_release_INVALID -a",
    ),
    (
        "os_validation_local_error_sim_kernel_manual_exit",
        "Simulate kernel check failure with forced non-zero exit",
        "check_kernel",
        "uname -r && uptime && echo 'INJECTED_ERROR: kernel check forced failure' >&2 && exit 21",
    ),
    (
        "os_validation_local_error_sim_cpu_bad_command",
        "Simulate CPU load check command-not-found error",
        "check_cpu_load",
        "toppp -bn1 | grep load",
    ),
    (
        "os_validation_local_error_sim_memory_bad_flag",
        "Simulate memory check failure using invalid free flag",
        "check_memory",
        "free --this-flag-does-not-exist",
    ),
    (
        "os_validation_local_error_sim_disk_invalid_path",
        "Simulate disk check failure by using invalid df argument",
        "check_disk",
        "df -h /this/path/does/not/exist/for-test",
    ),
    (
        "os_validation_local_error_sim_inode_invalid_flag",
        "Simulate inode check failure using invalid df option",
        "check_inode",
        "df --definitely-invalid-option",
    ),
    (
        "os_validation_local_error_sim_mounts_forced_fail",
        "Simulate mount list failure with explicit non-zero exit",
        "check_mounts",
        "mount && echo 'INJECTED_ERROR: mount stage failed intentionally' >&2 && exit 31",
    ),
    (
        "os_validation_local_error_sim_connectivity_unreachable",
        "Simulate connectivity check failure to unroutable IP",
        "check_connectivity",
        "ping -c 2 203.0.113.1",
    ),
    (
        "os_validation_local_error_sim_dns_invalid_domain",
        "Simulate DNS check failure with invalid domain",
        "check_dns",
        "ping -c 2 nonexistent-domain.invalid",
    ),
    (
        "os_validation_local_error_sim_ssh_service_missing",
        "Simulate SSH service check failure with wrong service name",
        "check_ssh",
        "systemctl is-active sshd_nonexistent_service",
    ),
    (
        "os_validation_local_error_sim_minio_health_wrong_port",
        "Simulate MinIO integration health failure with wrong port",
        "check_minio_health",
        "curl -f http://localhost:9199/minio/health/live",
    ),
    (
        "os_validation_local_error_sim_nfs_write_readonly",
        "Simulate NFS write check failure by writing to read-only filesystem",
        "check_nfs_write",
        "touch /sys/os_validation_testfile && rm /sys/os_validation_testfile",
    ),
]


for scenario_dag_id, scenario_desc, scenario_task, scenario_command in ERROR_SCENARIOS:
    globals()[scenario_dag_id] = build_error_injected_dag(
        dag_id=scenario_dag_id,
        description=scenario_desc,
        inject_task=scenario_task,
        injected_command=scenario_command,
    )
