"""
test_rag.py
Standalone test script for the RAG pipeline.
Run directly: python test_rag.py

No FastAPI, no uvicorn — just raw function calls.
"""

from log_parser import parse_airflow_log
from knowledge_base import build_knowledge_base
from rag_engine import run_rag_pipeline


# --- INPUT: Paste your full log text here ---
LOG_TEXT = """
 [2026-06-14T15:59:16.217+0000] {local_task_job_runner.py:120} INFO - ::group::Pre task execution logs
[2026-06-14T15:59:16.249+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=non-requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-14T15:59:06.405791 [queued]>
[2026-06-14T15:59:16.267+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-14T15:59:06.405791 [queued]>
[2026-06-14T15:59:16.271+0000] {taskinstance.py:2306} INFO - Starting attempt 1 of 1
[2026-06-14T15:59:16.301+0000] {taskinstance.py:2330} INFO - Executing <Task(SSHOperator): check_minio_health> on 2026-06-14 15:59:07.719093+00:00
[2026-06-14T15:59:16.321+0000] {warnings.py:110} WARNING - /home/***/.local/lib/python3.12/site-packages/***/task/task_runner/standard_task_runner.py:61: DeprecationWarning: This process (pid=1633) is multi-threaded, use of fork() may lead to deadlocks in the child.
  pid = os.fork()

[2026-06-14T15:59:16.326+0000] {standard_task_runner.py:63} INFO - Started process 1635 to run task
[2026-06-14T15:59:16.324+0000] {standard_task_runner.py:90} INFO - Running: ['***', 'tasks', 'run', 'minio_health_check', 'check_minio_health', 'manual__2026-06-14T15:59:06.405791', '--job-id', '345', '--raw', '--subdir', 'DAGS_FOLDER/minio_healthcheck_dag.py', '--cfg-path', '/tmp/tmpo4xv1nba']
[2026-06-14T15:59:16.329+0000] {standard_task_runner.py:91} INFO - Job 345: Subtask check_minio_health
[2026-06-14T15:59:16.450+0000] {task_command.py:426} INFO - Running <TaskInstance: minio_health_check.check_minio_health manual__2026-06-14T15:59:06.405791 [running]> on host db2db0122602
[2026-06-14T15:59:16.643+0000] {taskinstance.py:2648} INFO - Exporting env vars: AIRFLOW_CTX_DAG_OWNER='***' AIRFLOW_CTX_DAG_ID='minio_health_check' AIRFLOW_CTX_TASK_ID='check_minio_health' AIRFLOW_CTX_EXECUTION_DATE='2026-06-14T15:59:07.719093+00:00' AIRFLOW_CTX_TRY_NUMBER='1' AIRFLOW_CTX_DAG_RUN_ID='manual__2026-06-14T15:59:06.405791'
[2026-06-14T15:59:16.649+0000] {taskinstance.py:430} INFO - ::endgroup::
[2026-06-14T15:59:16.655+0000] {ssh.py:151} INFO - Creating ssh_client
[2026-06-14T15:59:16.657+0000] {ssh.py:124} INFO - ssh_hook is not provided or invalid. Trying ssh_conn_id to create SSHHook.
[2026-06-14T15:59:16.678+0000] {base.py:84} INFO - Using connection ID 'worker_node_192_168_1_5' for task execution.
[2026-06-14T15:59:16.683+0000] {ssh.py:301} WARNING - No Host Key Verification. This won't protect against Man-In-The-Middle attacks
[2026-06-14T15:59:16.708+0000] {transport.py:1909} INFO - Connected (version 2.0, client OpenSSH_10.2p1)
[2026-06-14T15:59:16.859+0000] {transport.py:1909} INFO - Authentication (password) successful!
[2026-06-14T15:59:16.862+0000] {ssh.py:480} INFO - Running command: curl -f http://localhost:9000/minio/health/live
[2026-06-14T15:59:17.042+0000] {ssh.py:526} INFO - curl: (7) Failed to connect to localhost port 9000 after 0 ms: Could not connect to server
[2026-06-14T15:59:17.085+0000] {taskinstance.py:441} INFO - ::group::Post task execution logs
[2026-06-14T15:59:17.114+0000] {taskinstance.py:2905} ERROR - Task failed with exception
Traceback (most recent call last):
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py", line 465, in _execute_task
    result = _execute_callable(context=context, **execute_callable_kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py", line 432, in _execute_callable
    return execute_callable(context=context, **execute_callable_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/baseoperator.py", line 400, in wrapper
    return func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 191, in execute
    result = self.run_ssh_client_command(ssh_client, self.command, context=context)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 179, in run_ssh_client_command
    self.raise_for_status(exit_status, agg_stderr, context=context)
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py", line 173, in raise_for_status
    raise AirflowException(f"SSH operator error: exit status = {exit_status}")
airflow.exceptions.AirflowException: SSH operator error: exit status = 7
[2026-06-14T15:59:17.126+0000] {taskinstance.py:1206} INFO - Marking task as FAILED. dag_id=minio_health_check, task_id=check_minio_health, run_id=manual__2026-06-14T15:59:06.405791, execution_date=20260614T155907, start_date=20260614T155916, end_date=20260614T155917
[2026-06-14T15:59:17.169+0000] {standard_task_runner.py:110} ERROR - Failed to execute job 345 for task check_minio_health (SSH operator error: exit status = 7; 1635)
[2026-06-14T15:59:17.229+0000] {local_task_job_runner.py:240} INFO - Task exited with return code 1
[2026-06-14T15:59:17.281+0000] {taskinstance.py:3498} INFO - 0 downstream tasks scheduled from follow-on schedule check
[2026-06-14T15:59:17.292+0000] {local_task_job_runner.py:222} INFO - ::endgroup::
"""

# --- INPUT: Set your task_id here ---
TASK_ID = "check_minio_health"


def pretty_print_candidate_lines(candidate_lines: list):
    print("\n" + "=" * 60)
    print("CANDIDATE LINES EXTRACTED FROM LOG")
    print("=" * 60)
    if not candidate_lines:
        print("[!] No candidate lines extracted.")
        return
    for i, line in enumerate(candidate_lines, 1):
        print(f"  {i}. {line}")


def pretty_print_result(result: dict):
    print("\n" + "=" * 60)
    print("RAG PIPELINE RESULT")
    print("=" * 60)
    #print(f"Error Location : {result['error_location']}")
    #print(f"Error Type     : {result['error_type']}")
    #print(f"Error Message  : {result['error_message']}")
    #print(f"Sources        : {result['retrieved_sources']}")

    matches = result.get("matches", [])
    if not matches:
        print("\n[!] No KB matches found above similarity threshold.")
        return

    print(f"\n{len(matches)} KB match(es) found:\n")
    for i, match in enumerate(matches, 1):
        print(f"  Match {i}")
        print(f"  {'─' * 50}")
        print(f"  Matched Log Line : {match['matched_line']}")
        print(f"  Similarity       : {match['similarity']}")
        print(f"  KB Document      : {match['kb_document']}")
        print(f"  Error Type       : {match['error_type']}")
        print(f"  Severity         : {match['severity']}")
        print(f"  Source           : {match['source']}")
        print(f"\n  Diagnosis  : {match['diagnosis']}")
        print(f"\n  Solution   : {match['solution']}")
        print(f"\n  Prevention : {match['prevention']}")
        if match['retrieved_sources']:
            print(f"\n  References : {match['retrieved_sources']}")
        print()


if __name__ == "__main__":
    # Step 1: Build knowledge base
    print("[*] Building knowledge base...")
    chroma_client = build_knowledge_base(persist_dir="./chroma_db")
    print("[*] Knowledge base ready.\n")

    # Step 2: Parse the log
    print("[*] Parsing log...")
    parsed_error = parse_airflow_log(LOG_TEXT)
    parsed_error.task_id = TASK_ID

    #print(f"    DAG ID      : {parsed_error.dag_id}")
    #print(f"    Task ID     : {parsed_error.task_id}")
    #print(f"    Error Type  : {parsed_error.error_type}")
    #print(f"    Error Msg   : {parsed_error.error_message}")
    #print(f"    File        : {parsed_error.file_path}")
    #print(f"    Line No     : {parsed_error.line_number}")

    # Step 3: Show candidate lines (useful for debugging what gets sent to ChromaDB)
    pretty_print_candidate_lines(parsed_error.candidate_lines)

    # Step 4: Run RAG pipeline
    print("\n[*] Running RAG pipeline...")
    result = run_rag_pipeline(
        parsed_error=parsed_error,
        chroma_client=chroma_client,
        top_k=1,
    )

    # Step 5: Print results
    pretty_print_result(result)
