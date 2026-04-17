"""
Production-ready local OS validation DAG for Ubuntu.
Runs system, storage, network, service, and integration checks on the local machine.
"""

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

# Canonical list of all validation task_ids (including TaskGroup prefixes)
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
    Collects state and output for all validation checks.
    Raises an exception when at least one check fails so the failure handler can run with ONE_FAILED.
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
    Emits structured failure JSON for downstream ingestion systems (e.g., RAG pipeline simulation).
    """
    dag_run = context["dag_run"]
    task_instance = context["ti"]

    # Prefer aggregate output if available.
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


with DAG(
    dag_id="os_validation_local_dag",
    default_args=default_args,
    description="Local Ubuntu OS validation DAG using BashOperator and PythonOperator",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["local", "validation", "os", "ubuntu"],
) as dag:
    # Entry point task
    start = EmptyOperator(task_id="start")

    # -------------------------
    # System checks TaskGroup
    # -------------------------
    with TaskGroup(group_id="system_checks") as system_checks:
        check_os_version = BashOperator(
            task_id="check_os_version",
            bash_command="lsb_release -a",
            do_xcom_push=True,
        )
        check_kernel = BashOperator(
            task_id="check_kernel",
            bash_command="uname -r && uptime",
            do_xcom_push=True,
        )
        check_cpu_load = BashOperator(
            task_id="check_cpu_load",
            bash_command="top -bn1 | grep load",
            do_xcom_push=True,
        )
        check_memory = BashOperator(
            task_id="check_memory",
            bash_command="free -m",
            do_xcom_push=True,
        )

    # --------------------------
    # Storage checks TaskGroup
    # --------------------------
    with TaskGroup(group_id="storage_checks") as storage_checks:
        check_disk = BashOperator(
            task_id="check_disk",
            bash_command="df -h",
            do_xcom_push=True,
        )
        check_inode = BashOperator(
            task_id="check_inode",
            bash_command="df -i",
            do_xcom_push=True,
        )
        check_mounts = BashOperator(
            task_id="check_mounts",
            bash_command="mount",
            do_xcom_push=True,
        )
        check_nfs = BashOperator(
            task_id="check_nfs",
            bash_command="mount | grep nfs || echo 'No NFS mount found'",
            do_xcom_push=True,
        )

    # --------------------------
    # Network checks TaskGroup
    # --------------------------
    with TaskGroup(group_id="network_checks") as network_checks:
        check_connectivity = BashOperator(
            task_id="check_connectivity",
            bash_command="ping -c 2 8.8.8.8",
            do_xcom_push=True,
        )
        check_dns = BashOperator(
            task_id="check_dns",
            bash_command="ping -c 2 google.com",
            do_xcom_push=True,
        )
        check_ports = BashOperator(
            task_id="check_ports",
            bash_command="ss -tuln | grep -E '22|9000|9001' || echo 'Ports not found'",
            do_xcom_push=True,
        )

    # --------------------------
    # Service checks TaskGroup
    # --------------------------
    with TaskGroup(group_id="service_checks") as service_checks:
        check_docker = BashOperator(
            task_id="check_docker",
            bash_command="systemctl is-active docker || echo 'Docker not running'",
            do_xcom_push=True,
        )
        check_ssh = BashOperator(
            task_id="check_ssh",
            bash_command="systemctl is-active ssh",
            do_xcom_push=True,
        )
        check_processes = BashOperator(
            task_id="check_processes",
            bash_command="ps aux | grep minio || echo 'MinIO not running'",
            do_xcom_push=True,
        )
        check_failed_services = BashOperator(
            task_id="check_failed_services",
            bash_command="systemctl --failed || echo 'No failed services'",
            do_xcom_push=True,
        )

    # --------------------------------
    # Integration checks (post-groups)
    # --------------------------------
    with TaskGroup(group_id="integration_checks") as integration_checks:
        check_minio_health = BashOperator(
            task_id="check_minio_health",
            bash_command="curl -f http://localhost:9000/minio/health/live || echo 'MinIO not reachable'",
            do_xcom_push=True,
        )
        check_nfs_write = BashOperator(
            task_id="check_nfs_write",
            bash_command="touch /tmp/testfile && rm /tmp/testfile",
            do_xcom_push=True,
        )

    # Aggregation must run regardless of upstream failures.
    aggregate_results = PythonOperator(
        task_id="aggregate_results",
        python_callable=aggregate_validation_results,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    # Failure handler runs only when aggregate_results fails (i.e., any validation failed).
    failure_handler = PythonOperator(
        task_id="failure_handler",
        python_callable=failure_handler_fn,
        trigger_rule=TriggerRule.ONE_FAILED,
    )

    # DAG flow:
    # start -> 4 parallel TaskGroups -> integration checks -> aggregate -> failure handler
    start >> [system_checks, storage_checks, network_checks, service_checks]
    [system_checks, storage_checks, network_checks, service_checks] >> integration_checks
    integration_checks >> aggregate_results >> failure_handler
