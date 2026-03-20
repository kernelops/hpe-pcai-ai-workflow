"""
Error-injected DAG for deploying distributed MinIO instances using SSHOperator.
Structure intentionally mirrors distributed_minio_deployment.
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
    dag_id='distributed_minio_deployment_error_injected',
    default_args=default_args,
    description='Deploy MinIO on worker nodes via SSH (error-injected)',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['minio', 'deployment', 'ssh', 'error-injected'],
) as dag:

    # Task 1: Create storage directory on worker 1
    create_storage_worker1 = SSHOperator(
        task_id='create_storage_worker1',
        ssh_conn_id='worker1',
        command='mkdir -p /tmp/minio-data-worker1',
    )

    # Task 2: Deploy MinIO container on worker 1
    deploy_minio_worker1 = SSHOperator(
        task_id='deploy_minio_worker1',
        ssh_conn_id='worker1',
        command='''
docker rm -f minio_worker1 || true
docker run -d \\
--name minio_worker1 \\
-p 9100:9000 \\
-p 9101:9001 \\
-e MINIO_ROOT_USER=admin \\
-e MINIO_ROOT_PASSWORD=password123 \\
-v /tmp/minio-data-worker1:/data \\
minio/minio server /data --console-address ":9001"
        ''',
    )

    # Task 3: Create storage directory on worker 2
    create_storage_worker2 = SSHOperator(
        task_id='create_storage_worker2',
        ssh_conn_id='worker2',
        command='mkdir -p /tmp/minio-data-worker2',
    )

    # Task 4: Deploy MinIO container on worker 2
    deploy_minio_worker2 = SSHOperator(
        task_id='deploy_minio_worker2',
        ssh_conn_id='worker2',
        command='''
docker rm -f minio_worker2 || true
docker run -d \\
--name minio_worker2 \\
-p 9200:9000 \\
-p 9201:9001 \\
-e MINIO_ROOT_USER=admin \\
-e MINIO_ROOT_PASSWORD=password123 \\
-v /tmp/minio-data-worker2:/data \\
minio/minio server /data --console-address ":9001"
        ''',
    )

    # Task 5: Health check worker 1
    health_check_worker1 = SSHOperator(
        task_id='health_check_worker1',
        ssh_conn_id='worker1',
        command='sleep 5 && curl -f http://localhost:9100/minio/health/live',
    )

    # Task 6: Health check worker 2 (intentionally fails for log-testing)
    health_check_worker2 = SSHOperator(
        task_id='health_check_worker2',
        ssh_conn_id='worker2',
        command='''
sleep 5
curl -f http://localhost:9200/minio/health/live
echo "INJECTED_ERROR: forcing failure after successful health check on worker2" >&2
exit 42
        ''',
    )

    # Task flow dependencies
    create_storage_worker1 >> deploy_minio_worker1 >> health_check_worker1
    create_storage_worker2 >> deploy_minio_worker2 >> health_check_worker2
