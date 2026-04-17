import os
import glob
import re

def refactor_dags():
    dags_path = "d:/HPE_project/hpe-pcai-ai-workflow/airflow/dags"
    files = glob.glob(os.path.join(dags_path, "*.py"))
    
    for f in files:
        if "deployment_workflow" in f or "refactor" in f:
            continue
            
        with open(f, 'r', encoding='utf-8') as fp:
            content = fp.read()
            
        if "get_worker_nodes" in content:
            continue
            
        if "worker1" not in content and "worker2" not in content and "NFS" not in f.upper():
            continue
            
        print(f"Refactoring {os.path.basename(f)}...")
        
        # 1. Add imports
        if "from airflow.models import Connection" not in content:
            content = re.sub(r'^(import .*?\n|from .*?\n)', 
                             r"import os\nimport requests\nfrom airflow.models import Connection\nfrom airflow.operators.python import PythonOperator\nfrom airflow.utils.session import provide_session\n\g<1>", 
                             content, count=1, flags=re.MULTILINE)
        
        # Replace hardcoded parts
        content = content.replace("worker1", "node")
        content = content.replace("worker2", "node")
        content = content.replace("9100", "9000")
        content = content.replace("9101", "9001")
        content = content.replace("9200", "9000")
        content = content.replace("9201", "9001")
        
        # 2. Add functions
        functions = """
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

"""
        content = re.sub(r'(default_args\s*=)', functions + r'\1', content, count=1)
        
        # 3. Add dynamic tasks inside DAG
        dag_tasks = """
    get_nodes = PythonOperator(
        task_id="get_worker_nodes",
        python_callable=get_worker_nodes,
    )

    create_connections = PythonOperator(
        task_id="create_airflow_connections",
        python_callable=create_airflow_connections,
    )
"""
        content = re.sub(r'(with DAG.*?:[\s\n]+)', r'\1' + dag_tasks, content, flags=re.DOTALL)
        
        if "SSHOperator" in content and "assign_node_roles" not in content and 'nfs' not in f.lower() and 'NFS.py' not in f:
            content = re.sub(r'(\w+)\s*=\s*(Dynamic)?SSHOperator\(', r'\1 = \2SSHOperator.partial(', content)
            content = re.sub(r'\s*ssh_conn_id\s*=\s*[\'"]node[\'"]\s*,?\n?', '\n', content)
            content = re.sub(r'(\s{4})\)\n\n', r'\1).expand(ssh_conn_id=create_connections.output)\n\n', content)
            content = re.sub(r'(\s{4})\)\n(\s{4}[a-zA-Z_]+\s*=\s*SSHOperator)', r'\1).expand(ssh_conn_id=create_connections.output)\n\2', content)
            content = re.sub(r'(\s{4})\)\n(\s*[a-zA-Z_]+ \>\>)', r'\1).expand(ssh_conn_id=create_connections.output)\n\2', content)

            last_line_match = re.search(r'^[ \t]*([a-zA-Z0-9_]+)\s*>>', content, flags=re.MULTILINE)
            if last_line_match and "get_nodes" not in last_line_match.group(0):
                first_task = last_line_match.group(1)
                deps_header = f"get_nodes >> create_connections >> {first_task}\n{last_line_match.group(0).split(first_task)[0]}"
                content = content[:last_line_match.start()] + deps_header + content[last_line_match.start() + len(last_line_match.group(0).split(first_task)[0]) + len(first_task):]
                
        # For NFS
        if 'NFS' in f.upper():
            nfs_func = """def assign_node_roles(**kwargs):
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
"""
            content = re.sub(r'def assign_node_roles\(\*\*kwargs\):.*?kwargs\[\'ti\'\]\.xcom_push\(key=\'server_host\'.*?\n', nfs_func, content, flags=re.DOTALL)
            
            if "assign_roles >>" in content:
                content = content.replace("assign_roles >>", "get_nodes >> create_connections >> assign_roles >>")

        with open(f, 'w', encoding='utf-8') as fp:
            fp.write(content)
            
    print("Done")

if __name__ == "__main__":
    refactor_dags()
