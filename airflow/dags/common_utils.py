import os
import requests
from datetime import timedelta
from airflow.models import Connection
from airflow.utils.session import provide_session

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
