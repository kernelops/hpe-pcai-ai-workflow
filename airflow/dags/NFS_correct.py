"""
DAG for dynamically distributing NFS Server and Client roles at runtime.
"""
import os
import requests
from airflow.operators.python import PythonOperator
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.hooks.base import BaseHook
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

class DynamicSSHOperator(SSHOperator):
    template_fields = tuple(set(SSHOperator.template_fields).union({'ssh_conn_id'}))


from common_utils import API_BASE, get_worker_nodes, create_airflow_connections, default_args

def assign_node_roles(**kwargs):
    import random
    nodes = kwargs['ti'].xcom_pull(task_ids='get_worker_nodes')
    if not nodes or len(nodes) < 1:
        print("No nodes available")
        return
        
    random.shuffle(nodes)
    server = f"worker_node_{nodes[0]['ip'].replace('.', '_')}"
    client = f"worker_node_{nodes[1]['ip'].replace('.', '_')}" if len(nodes) > 1 else server
    server_host = nodes[0]['ip']
    
    print(f"--- RUNTIME ALLOCATION ---")
    print(f"Allocated Server: {server}")
    print(f"Allocated Client: {client}")
    print(f"Server Host: {server_host}")
    print(f"--------------------------")
    
    kwargs['ti'].xcom_push(key='server', value=server)
    kwargs['ti'].xcom_push(key='client', value=client)
    kwargs['ti'].xcom_push(key='server_host', value=server_host)

with DAG(
    dag_id='nfs_dynamic_roles_deployment',
    default_args=default_args,
    description='Dynamically assign Server and Client roles for NFS deployment',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['nfs', 'docker', 'ssh', 'dynamic'],
) as dag:

    
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
    assign_roles = PythonOperator(
        task_id='assign_roles',
        python_callable=assign_node_roles,
    )

    create_server_storage = DynamicSSHOperator(
        task_id='create_server_storage',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='server') }}",
        command='mkdir -p /tmp/nfs-server-data && chmod 0777 /tmp/nfs-server-data'
    )

    deploy_server = DynamicSSHOperator(
        task_id='deploy_server',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='server') }}",
        cmd_timeout=30,
        command='''
docker rm -f nfs_server || true
docker run -d \\
--name nfs_server \\
--privileged \\
--network host \\
-v /lib/modules:/lib/modules:ro \\
-v /tmp/nfs-server-data:/data \\
    -e NFS_EXPORT_0='/data *(rw,sync,no_subtree_check,no_root_squash)' \\
erichough/nfs-server
        '''
    )

    verify_server_prerequisites = DynamicSSHOperator(
        task_id='verify_server_prerequisites',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='server') }}",
        command='''
echo "Ensuring NFS kernel modules are loaded..."
sudo modprobe nfs || true
sudo modprobe nfsd || true

if lsmod | grep -Eq '^nfsd?'; then
    echo "Kernel nfs module detected"
else
    echo "WARNING: kernel module 'nfs' could not be loaded. The container will try to load it."
fi
        '''
    )

    wait_for_server = DynamicSSHOperator(
        task_id='wait_for_server_boot',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='server') }}",
        cmd_timeout=30,
        command='''
for i in $(seq 1 15); do
  if docker ps -q -f name=nfs_server -f status=running | grep -q .; then
    echo "NFS server container is running (attempt $i)"
    if ss -tln | grep -q ':2049'; then
      echo "NFS port 2049 is listening - server is ready!"
      exit 0
    fi
  fi
  echo "Waiting for NFS server... (attempt $i/15)"
  sleep 2
done
echo "ERROR: NFS server failed to start. Logs:"
docker logs nfs_server 2>&1
exit 1
        '''
    )

    create_client_volume = DynamicSSHOperator(
        task_id='create_client_volume',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='client') }}",
        cmd_timeout=30,
        command='''
# Crucial: Destroy the old client container first so the volume is unlocked and can be deleted!
docker rm -f nfs_client_test || true
docker volume rm nfs_client_vol || true

docker volume create --driver local \\
  --opt type=nfs \\
    --opt o=addr={{ ti.xcom_pull(task_ids='assign_roles', key='server_host') }},rw,nolock,nfsvers=3 \\
  --opt device=:/data \\
  nfs_client_vol
        '''
    )

    test_client_mount = DynamicSSHOperator(
        task_id='test_client_mount',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='client') }}",
        cmd_timeout=60,
        command='''
docker rm -f nfs_client_test || true
docker run -d \\
--name nfs_client_test \\
-v nfs_client_vol:/mnt/nfs \\
alpine sleep 3600
        '''
    )

    write_test_file = DynamicSSHOperator(
        task_id='write_test_file',
        ssh_conn_id="{{ ti.xcom_pull(task_ids='assign_roles', key='client') }}",
        cmd_timeout=30,
        command='docker exec nfs_client_test sh -c "echo \\"Hello from the dynamically allocated client node!\\" > /mnt/nfs/test_file.txt"'
    )

    get_nodes >> create_connections >> assign_roles >> create_server_storage >> verify_server_prerequisites >> deploy_server
    deploy_server >> wait_for_server >> create_client_volume >> test_client_mount >> write_test_file