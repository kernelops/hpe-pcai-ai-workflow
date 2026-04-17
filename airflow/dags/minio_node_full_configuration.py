"""
DAG for deploying and configuring MinIO on node with advanced settings.
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
    dag_id='minio_node_full_configuration',
    default_args=default_args,
    description='Deploy and configure MinIO with advanced options on node',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['minio', 'node', 'configuration', 'ssh'],
) as dag:

    
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
    prepare_directories = SSHOperator.partial(
        task_id='prepare_directories',
        command='''
mkdir -p /tmp/minio-node/data1 /tmp/minio-node/data2 /tmp/minio-node/data3 /tmp/minio-node/data4
mkdir -p /tmp/minio-node/cache /tmp/minio-node/certs /tmp/minio-node/policies
        ''',
    ).expand(ssh_conn_id=create_connections.output)

    create_tls_certs = SSHOperator.partial(
        task_id='create_tls_certs',
        command='''
if [ ! -f /tmp/minio-node/certs/private.key ] || [ ! -f /tmp/minio-node/certs/public.crt ]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout /tmp/minio-node/certs/private.key \
    -out /tmp/minio-node/certs/public.crt \
    -days 365 \
    -subj "/CN=node-minio"
fi
cp /tmp/minio-node/certs/public.crt /tmp/minio-node/certs/public.cert
        ''',
    ).expand(ssh_conn_id=create_connections.output)

    deploy_minio = SSHOperator.partial(
        task_id='deploy_minio',
        command='''
docker rm -f minio_node || true
docker run -d \
  --name minio_node \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=password123 \
  -e MINIO_DOMAIN=minio.node.local \
  -e MINIO_CACHE_DRIVES=/cache \
  -e MINIO_PROMETHEUS_AUTH_TYPE=public \
  -e MINIO_AUDIT_WEBHOOK_ENABLE_primary=on \
  -e MINIO_AUDIT_WEBHOOK_ENDPOINT_primary=http://127.0.0.1:9999/minio/audit \
  -v /tmp/minio-node/data1:/data1 \
  -v /tmp/minio-node/data2:/data2 \
  -v /tmp/minio-node/data3:/data3 \
  -v /tmp/minio-node/data4:/data4 \
  -v /tmp/minio-node/cache:/cache \
  -v /tmp/minio-node/certs:/root/.minio/certs \
  minio/minio server \
  --address "0.0.0.0:9000" \
  --console-address "0.0.0.0:9001" \
  /data1 /data2 /data3 /data4
        ''',
    ).expand(ssh_conn_id=create_connections.output)

    health_check = SSHOperator.partial(
        task_id='health_check',
        command='sleep 8 && curl -k -f https://localhost:9000/minio/health/live',
    ).expand(ssh_conn_id=create_connections.output)

    configure_access_policies = SSHOperator.partial(
        task_id='configure_access_policies',
        command='''
cat > /tmp/minio-node/policies/custom-readonly.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::*/*"
      ]
    }
  ]
}
EOF

docker run --rm --network host \
  --entrypoint /bin/sh \
  -v /tmp/minio-node/policies:/policies \
  minio/mc \
  -c '
    mc --insecure alias set local https://127.0.0.1:9000 admin password123 &&
    mc --insecure admin user add local readonly_user readonly123 || true &&
    mc --insecure admin user add local readwrite_user readwrite123 || true &&
    mc --insecure admin policy create local custom-readonly /policies/custom-readonly.json || true &&
    mc --insecure admin policy attach local custom-readonly --user readonly_user || true &&
    mc --insecure admin policy attach local readwrite --user readwrite_user || true
  '
        ''',
    ).expand(ssh_conn_id=create_connections.output)

    configure_buckets_and_lifecycle = SSHOperator.partial(
        task_id='configure_buckets_and_lifecycle',
        command='''
docker run --rm --network host --entrypoint /bin/sh minio/mc -c '
  mc --insecure alias set local https://127.0.0.1:9000 admin password123 &&
  mc --insecure mb --ignore-existing local/main-bucket &&
  mc --insecure version enable local/main-bucket || true &&
  mc --insecure ilm rule add local/main-bucket --expire-days 30 || true &&
  mc --insecure mb --with-lock --ignore-existing local/compliance-bucket &&
  mc --insecure version enable local/compliance-bucket || true &&
  mc --insecure retention set --default GOVERNANCE 30d local/compliance-bucket || true
'
        ''',
    ).expand(ssh_conn_id=create_connections.output)

    validate_metrics_endpoint = SSHOperator.partial(
        task_id='validate_metrics_endpoint',
        command='curl -k -f https://localhost:9000/minio/v2/metrics/cluster > /dev/null',
    ).expand(ssh_conn_id=create_connections.output)

    get_nodes >> create_connections >> prepare_directories \
     >> create_tls_certs >> deploy_minio >> health_check
    health_check >> configure_access_policies >> configure_buckets_and_lifecycle >> validate_metrics_endpoint
