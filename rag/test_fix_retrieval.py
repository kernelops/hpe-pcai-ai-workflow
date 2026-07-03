import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag_engine import retrieve_fix_context
from knowledge_base import build_knowledge_base

TEST_TASK_ID = "check_minio_health"
TEST_RAW_LOG = """
[2026-06-26T05:34:40.061+0000] {local_task_job_runner.py:120} INFO - ::group::Pre task execution logs
[2026-06-26T05:34:40.115+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=non-requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [queued]>
[2026-06-26T05:34:40.139+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [queued]>
[2026-06-26T05:34:40.142+0000] {taskinstance.py:2306} INFO - Starting attempt 1 of 1\n
[2026-06-26T05:34:40.191+0000] {taskinstance.py:2330} INFO - Executing <Task(SSHOperator): check_minio_health> on 2026-06-26 05:34:30.932255+00:00
[2026-06-26T05:34:40.222+0000] {warnings.py:110} WARNING - /home/***/.local/lib/python3.12/site-packages/***/task/task_runner/standard_task_runner.py:61: DeprecationWarning: This process (pid=366) is multi-threaded, use of fork() may lead to deadlocks in the child.
pid = os.fork()

[2026-06-26T05:34:40.233+0000] {standard_task_runner.py:63} INFO - Started process 368 to run task
[2026-06-26T05:34:40.230+0000] {standard_task_runner.py:90} INFO - Running: [\'***\', \'tasks\', \'run\', \'minio_health_check\', \'check_minio_health\', \'manual__2026-06-26T05:34:29.072153\', \'--job-id\', \'379\', \'--raw\', \'--subdir\', \'DAGS_FOLDER/minio_healthcheck_dag.py\', \'--cfg-path\', \'/tmp/tmpp4sas9eq\']
[2026-06-26T05:34:40.238+0000] {standard_task_runner.py:91} INFO - Job 379: Subtask check_minio_health
[2026-06-26T05:34:40.399+0000] {task_command.py:426} INFO - Running <TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [running]> on host db2db0122602\n[2026-06-26T05:34:40.630+0000] {taskinstance.py:2648} INFO - Exporting env vars: AIRFLOW_CTX_DAG_OWNER=\'***\' AIRFLOW_CTX_DAG_ID=\'minio_health_check\' AIRFLOW_CTX_TASK_ID=\'check_minio_health\' AIRFLOW_CTX_EXECUTION_DATE=\'2026-06-26T05:34:30.932255+00:00\' AIRFLOW_CTX_TRY_NUMBER=\'1\' AIRFLOW_CTX_DAG_RUN_ID=\'manual__2026-06-26T05:34:29.072153\'
[2026-06-26T05:34:40.637+0000] {taskinstance.py:430} INFO - ::endgroup::\
[2026-06-26T05:34:40.640+0000] {ssh.py:151} INFO - Creating ssh_client
[2026-06-26T05:34:40.642+0000] {ssh.py:124} INFO - ssh_hook is not provided or invalid. Trying ssh_conn_id to create SSHHook.
[2026-06-26T05:34:40.664+0000] {base.py:84} INFO - Using connection ID \'worker_node_192_168_1_5\' for task execution.
[2026-06-26T05:34:40.668+0000] {ssh.py:301} WARNING - No Host Key Verification. This won\'t protect against Man-In-The-Middle attacks
[2026-06-26T05:34:40.705+0000] {transport.py:1909} INFO - Connected (version 2.0, client OpenSSH_10.2p1)
[2026-06-26T05:34:40.965+0000] {transport.py:1909} INFO - Authentication (password) successful!
[2026-06-26T05:34:40.971+0000] {ssh.py:480} INFO - Running command: curl -f http://localhost:9000/minio/health/live
[2026-06-26T05:34:41.148+0000] {ssh.py:526} INFO - curl: (7) Failed to connect to localhost port 9000 after 2 ms: Could not connect to server
[2026-06-26T05:34:41.193+0000] {taskinstance.py:441} INFO - ::group::Post task execution logs
[2026-06-26T05:34:41.225+0000] {taskinstance.py:2905} ERROR - Task failed with exception
Traceback (most recent call last):\
 File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py", line 465, in _execute_task\n    result = _execute_callable(context=context, **execute_callable_kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\
File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py", line 432, in _execute_callable
    return execute_callable(context=context, **execute_callable_kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/baseoperator.py", line 400, in wrapper\n    return func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 191, in execute
    result = self.run_ssh_client_command(ssh_client, self.command, context=context)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 179, in run_ssh_client_command
    self.raise_for_status(exit_status, agg_stderr, context=context)
File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 173, in raise_for_status
    raise AirflowException(f"SSH operator error: exit status = {exit_status}")
airflow.exceptions.AirflowException: SSH operator error: exit status = 7
[2026-06-26T05:34:41.240+0000] {taskinstance.py:1206} INFO - Marking task as FAILED. dag_id=minio_health_check, task_id=check_minio_health, run_id=manual__2026-06-26T05:34:29.072153, execution_date=20260626T053430, start_date=20260626T053440, end_date=20260626T053441
[2026-06-26T05:34:41.281+0000] {standard_task_runner.py:110} ERROR - Failed to execute job 379 for task check_minio_health (SSH operator error: exit status = 7; 368)
[2026-06-26T05:34:41.342+0000] {local_task_job_runner.py:240} INFO - Task exited with return code 1
[2026-06-26T05:34:41.404+0000] {taskinstance.py:3498} INFO - 0 downstream tasks scheduled from follow-on schedule check
[2026-06-26T05:34:41.417+0000] {local_task_job_runner.py:222} INFO - ::endgroup::' 
"""

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 TESTING RAG RETRIEVAL")

    print("\n[TEST] Building knowledge base...")
    chroma_client = build_knowledge_base(persist_dir="./chroma_db")
    
    try:
        results = retrieve_fix_context(
            task_id=TEST_TASK_ID,
            raw_log=TEST_RAW_LOG,
            client=chroma_client
        )
        
        print(f"\n✅ Found {len(results)} match(es)\n")
        
        for i, result in enumerate(results, 1):
            print(f"Match {i}:")
            print(f"  ID: {result.get('task_id', 'N/A')}")
            print(f"  Similarity: {result.get('similarity', 'N/A')}")
            print("-"*40)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()