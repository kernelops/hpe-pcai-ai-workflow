"""
Suite of error-injected DAGs for MinIO node full configuration.
Each DAG mirrors minio_node_full_configuration and injects a distinct failure mode.
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
    'retry_delay': timedelta(seconds=30),
}


def build_error_injected_dag(dag_id: str, description: str, inject_task: str, injected_command: str) -> DAG:
    prepare_command = injected_command if inject_task == 'prepare_directories' else '''
mkdir -p /tmp/minio-node/data1 /tmp/minio-node/data2 /tmp/minio-node/data3 /tmp/minio-node/data4
mkdir -p /tmp/minio-node/cache /tmp/minio-node/certs /tmp/minio-node/policies
    '''

    tls_command = injected_command if inject_task == 'create_tls_certs' else '''
if [ ! -f /tmp/minio-node/certs/private.key ] || [ ! -f /tmp/minio-node/certs/public.crt ]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout /tmp/minio-node/certs/private.key \
    -out /tmp/minio-node/certs/public.crt \
    -days 365 \
    -subj "/CN=node-minio"
fi
cp /tmp/minio-node/certs/public.crt /tmp/minio-node/certs/public.cert
    '''

    deploy_command = injected_command if inject_task == 'deploy_minio' else '''
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
    '''

    health_command = injected_command if inject_task == 'health_check' else 'sleep 8 && curl -k -f https://localhost:9000/minio/health/live'

    access_command = injected_command if inject_task == 'configure_access_policies' else '''
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
    '''

    lifecycle_command = injected_command if inject_task == 'configure_buckets_and_lifecycle' else '''
docker run --rm --network host --entrypoint /bin/sh minio/mc -c '
  mc --insecure alias set local https://127.0.0.1:9000 admin password123 &&
  mc --insecure mb --ignore-existing local/main-bucket &&
  mc --insecure version enable local/main-bucket || true &&
  mc --insecure ilm rule add local/main-bucket --expire-days 30 || true &&
  mc --insecure mb --with-lock --ignore-existing local/compliance-bucket &&
  mc --insecure version enable local/compliance-bucket || true &&
  mc --insecure retention set --default GOVERNANCE 30d local/compliance-bucket || true
'
    '''

    metrics_command = injected_command if inject_task == 'validate_metrics_endpoint' else 'curl -k -f https://localhost:9000/minio/v2/metrics/cluster > /dev/null'

    with DAG(
        dag_id=dag_id,
        default_args=default_args,
        description=description,
        schedule_interval=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=['minio', 'node', 'configuration', 'ssh', 'error-injected'],
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
            command=prepare_command,
        ).expand(ssh_conn_id=create_connections.output)

        create_tls_certs = SSHOperator.partial(
            task_id='create_tls_certs',
            command=tls_command,
        ).expand(ssh_conn_id=create_connections.output)

        deploy_minio = SSHOperator.partial(
            task_id='deploy_minio',
            command=deploy_command,
        ).expand(ssh_conn_id=create_connections.output)

        health_check = SSHOperator.partial(
            task_id='health_check',
            command=health_command,
        ).expand(ssh_conn_id=create_connections.output)

        configure_access_policies = SSHOperator.partial(
            task_id='configure_access_policies',
            command=access_command,
        ).expand(ssh_conn_id=create_connections.output)

        configure_buckets_and_lifecycle = SSHOperator.partial(
            task_id='configure_buckets_and_lifecycle',
            command=lifecycle_command,
        ).expand(ssh_conn_id=create_connections.output)

        validate_metrics_endpoint = SSHOperator.partial(
            task_id='validate_metrics_endpoint',
            command=metrics_command,
        ).expand(ssh_conn_id=create_connections.output)

        get_nodes >> create_connections >> prepare_directories \
             >> create_tls_certs >> deploy_minio >> health_check
        health_check >> configure_access_policies >> configure_buckets_and_lifecycle >> validate_metrics_endpoint

    return dag


ERROR_SCENARIOS = [
    (
        'minio_node_error_sim_missing_command_prepare',
        'Simulate command-not-found during directory preparation',
        'prepare_directories',
        '''
mkdir -p /tmp/minio-node/data1
non_existing_binary_for_test --init
        ''',
    ),
    (
        'minio_node_error_sim_tls_bad_flag',
        'Simulate TLS certificate generation failure with invalid OpenSSL flag',
        'create_tls_certs',
        '''
openssl req --definitely-invalid-flag -x509 -nodes -newkey rsa:2048 \
  -keyout /tmp/minio-node/certs/private.key \
  -out /tmp/minio-node/certs/public.crt \
  -days 365 \
  -subj "/CN=node-minio"
        ''',
    ),
    (
        'minio_node_error_sim_docker_invalid_image',
        'Simulate container pull failure with invalid MinIO image',
        'deploy_minio',
        '''
docker rm -f minio_node || true
docker run -d \
  --name minio_node \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=password123 \
  -v /tmp/minio-node/data1:/data \
  minio/minio:this-tag-does-not-exist server /data --console-address ":9001"
        ''',
    ),
    (
        'minio_node_error_sim_health_wrong_port',
        'Simulate health-check network failure by querying wrong port',
        'health_check',
        'sleep 5 && curl -k -f https://localhost:9199/minio/health/live',
    ),
    (
        'minio_node_error_sim_policy_auth_failure',
        'Simulate access policy step failure due to invalid credentials',
        'configure_access_policies',
        '''
docker run --rm --network host --entrypoint /bin/sh minio/mc -c '
  mc --insecure alias set local https://127.0.0.1:9000 admin wrong-password &&
  mc --insecure admin user add local readonly_user readonly123
'
        ''',
    ),
    (
        'minio_node_error_sim_policy_malformed_json',
        'Simulate policy creation failure due to malformed JSON file',
        'configure_access_policies',
        '''
cat > /tmp/minio-node/policies/custom-readonly.json <<'EOF'
{ "Version": "2012-10-17", "Statement": [ { "Effect": "Allow"  ] }
EOF

docker run --rm --network host \
  --entrypoint /bin/sh \
  -v /tmp/minio-node/policies:/policies \
  minio/mc \
  -c '
    mc --insecure alias set local https://127.0.0.1:9000 admin password123 &&
    mc --insecure admin policy create local custom-readonly /policies/custom-readonly.json
  '
        ''',
    ),
    (
        'minio_node_error_sim_lifecycle_bad_retention',
        'Simulate lifecycle/retention configuration error with invalid retention mode',
        'configure_buckets_and_lifecycle',
        '''
docker run --rm --network host --entrypoint /bin/sh minio/mc -c '
  mc --insecure alias set local https://127.0.0.1:9000 admin password123 &&
  mc --insecure mb --ignore-existing local/compliance-bucket &&
  mc --insecure retention set --default INVALIDMODE 30d local/compliance-bucket
'
        ''',
    ),
    (
        'minio_node_error_sim_metrics_invalid_path',
        'Simulate metrics validation failure with invalid endpoint path',
        'validate_metrics_endpoint',
        'curl -k -f https://localhost:9000/minio/v2/metrics/nonexistent > /dev/null',
    ),
    (
        'minio_node_error_sim_manual_exit_after_policy',
        'Simulate explicit non-zero exit after successful policy step',
        'configure_access_policies',
        '''
docker run --rm --network host --entrypoint /bin/sh minio/mc -c '
  mc --insecure alias set local https://127.0.0.1:9000 admin password123
'
echo "INJECTED_ERROR: manual failure after policy stage" >&2
exit 42
        ''',
    ),
    (
        'minio_node_error_sim_shell_syntax_error',
        'Simulate shell syntax error in lifecycle step',
        'configure_buckets_and_lifecycle',
        '''
if [ -f /tmp/minio-node/policies/custom-readonly.json ]
then
  echo "Policy exists"
# missing fi on purpose
        ''',
    ),
]


for scenario_dag_id, scenario_desc, scenario_task, scenario_command in ERROR_SCENARIOS:
    globals()[scenario_dag_id] = build_error_injected_dag(
        dag_id=scenario_dag_id,
        description=scenario_desc,
        inject_task=scenario_task,
        injected_command=scenario_command,
    )
