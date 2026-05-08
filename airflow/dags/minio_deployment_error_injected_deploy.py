"""
Error-injected DAG variant for deploying distributed MinIO instances using SSHOperator.
Injection point: deploy_minio_node.
"""
import os
import requests
from airflow.operators.python import PythonOperator
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from datetime import datetime, timedelta


from common_utils import API_BASE, get_worker_nodes, create_airflow_connections, default_args

with DAG(
    dag_id='distributed_minio_deployment_error_injected_deploy_node',
    default_args=default_args,
    description='Deploy MinIO on worker nodes via SSH (error at deploy_minio_node)',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['minio', 'deployment', 'ssh', 'error-injected'],
) as dag:

    
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
    create_storage_node = SSHOperator.partial(
        task_id='create_storage_node',
        command='mkdir -p /tmp/minio-data-node',
    ).expand(ssh_conn_id=create_connections.output)

    deploy_minio_node = SSHOperator.partial(
        task_id='deploy_minio_node',
        command='''
docker rm -f minio_node || true
docker run -d \\
--name minio_node \\
-p 9000:9000 \\
-p 9001:9001 \\
-e MINIO_ROOT_USER=admin \\
-e MINIO_ROOT_PASSWORD=password123 \\
-v /tmp/minio-data-node:/data \\
minio/minio server /data --console-address ":9001"
echo "INJECTED_ERROR: forcing failure in deploy_minio_node" >&2
exit 31
        ''',
    ).expand(ssh_conn_id=create_connections.output)



    health_check_node = SSHOperator.partial(
        task_id='health_check_node',
        command='sleep 5 && curl -f http://localhost:9000/minio/health/live',
    ).expand(ssh_conn_id=create_connections.output)


    get_nodes >> create_connections >> create_storage_node \
     >> deploy_minio_node >> health_check_node
