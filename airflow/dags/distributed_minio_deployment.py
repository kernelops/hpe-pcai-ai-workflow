"""
DAG for deploying distributed MinIO instances using SSHOperator.
"""
import os
import requests
from airflow.models import Connection
from airflow.operators.python import PythonOperator
from airflow.utils.session import provide_session
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from datetime import datetime, timedelta


API_BASE = os.getenv("BACKEND_API_BASE", "http://host.docker.internal:8000")

def get_worker_nodes(**context):
    dag_run = context.get("dag_run")
    dag_conf = dag_run.conf or {} if dag_run else {}
    conf_nodes = dag_conf.get("worker_nodes") or []
    if conf_nodes:
        return [n for n in conf_nodes if n.get("ip") and n.get("username")]
    try:
        response = requests.get(f"{API_BASE}/nodes", timeout=15)
        response.raise_for_status()
        nodes = response.json()
        return [n for n in nodes if n.get("status") == "reachable"]
    except Exception as exc:
        print(f"Error fetching nodes: {exc}")
        return []

@provide_session
def create_airflow_connections(session=None, **context):
    nodes = context["task_instance"].xcom_pull(task_ids="get_worker_nodes")
    conn_ids = []
    if not nodes:
        return conn_ids
    for node in nodes:
        ip = node["ip"]
        username = node["username"]
        password = node.get("password", "")
        conn_id = f"worker_node_{ip.replace('.', '_')}"
        existing = session.query(Connection).filter(Connection.conn_id == conn_id).first()
        if not existing:
            session.add(Connection(
                conn_id=conn_id, conn_type="ssh", host=ip, login=username, password=password, port=22
            ))
            session.commit()
        conn_ids.append(conn_id)
    return conn_ids

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

with DAG(
    dag_id='distributed_minio_deployment',
    default_args=default_args,
    description='Deploy MinIO on worker nodes via SSH',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['minio', 'deployment', 'ssh'],
) as dag:

    
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
# Task 1: Create storage directory on worker 1
    create_storage_node = SSHOperator.partial(
        task_id='create_storage_node',
        command='mkdir -p /tmp/minio-data-node',
    ).expand(ssh_conn_id=create_connections.output)

    # Task 2: Deploy MinIO container on worker 1
    # Added docker rm -f to ensure idempotency if container exists
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
        ''',
    ).expand(ssh_conn_id=create_connections.output)



    # Task 5: Health check worker 1
    health_check_node = SSHOperator.partial(
        task_id='health_check_node',
        command='sleep 5 && curl -f http://localhost:9000/minio/health/live',
    ).expand(ssh_conn_id=create_connections.output)


    # Task flow dependencies
    get_nodes >> create_connections >> create_storage_node \
     >> deploy_minio_node >> health_check_node
