"""
Error-injected DAG for cleaning up distributed MinIO instances using SSHOperator.
Structure intentionally mirrors distributed_minio_cleanup.
"""
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(seconds=30),
}

with DAG(
    dag_id='distributed_minio_cleanup_error_injected',
    default_args=default_args,
    description='Cleanup MinIO on worker nodes via SSH (error-injected)',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['minio', 'cleanup', 'ssh', 'error-injected'],
) as dag:

    # Task 1: Stop worker 1
    stop_worker1 = SSHOperator(
        task_id='stop_worker1',
        ssh_conn_id='worker1',
        command='docker stop minio_worker1 || true',
    )

    # Task 2: Remove worker 1
    remove_worker1 = SSHOperator(
        task_id='remove_worker1',
        ssh_conn_id='worker1',
        command='docker rm minio_worker1 || true',
    )

    # Task 3: Remove storage worker 1
    remove_storage_worker1 = SSHOperator(
        task_id='remove_storage_worker1',
        ssh_conn_id='worker1',
        command='rm -rf /tmp/minio-data-worker1 || true',
    )

    # Task 4: Stop worker 2
    stop_worker2 = SSHOperator(
        task_id='stop_worker2',
        ssh_conn_id='worker2',
        command='docker stop minio_worker2 || true',
    )

    # Task 5: Remove worker 2
    remove_worker2 = SSHOperator(
        task_id='remove_worker2',
        ssh_conn_id='worker2',
        command='docker rm minio_worker2 || true',
    )

    # Task 6: Remove storage worker 2 (intentionally fails for log-testing)
    remove_storage_worker2 = SSHOperator(
        task_id='remove_storage_worker2',
        ssh_conn_id='worker2',
        command='''
rm -rf /tmp/minio-data-worker2 || true
echo "INJECTED_ERROR: simulated cleanup failure on worker2" >&2
exit 43
        ''',
    )

    # Task flow dependencies
    stop_worker1 >> remove_worker1 >> remove_storage_worker1
    stop_worker2 >> remove_worker2 >> remove_storage_worker2
