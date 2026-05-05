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
 /opt/airflow/logs/dag_id=deployment_workflow/run_id=manual__2026-05-05T08:37:46.600216/task_id=simulate_os_validation_error/map_index=0/attempt=1.log
[2026-05-05T08:38:09.756+0000] {local_task_job_runner.py:120} INFO - ::group::Pre task execution logs
[2026-05-05T08:38:09.862+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=non-requeueable deps ti=<TaskInstance: deployment_workflow.simulate_os_validation_error manual__2026-05-05T08:37:46.600216 map_index=0 [queued]>
[2026-05-05T08:38:09.923+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=requeueable deps ti=<TaskInstance: deployment_workflow.simulate_os_validation_error manual__2026-05-05T08:37:46.600216 map_index=0 [queued]>
[2026-05-05T08:38:09.934+0000] {taskinstance.py:2306} INFO - Starting attempt 1 of 1
[2026-05-05T08:38:10.008+0000] {taskinstance.py:2330} INFO - Executing <Mapped(SSHOperator): simulate_os_validation_error> on 2026-05-05 08:37:47.990735+00:00
[2026-05-05T08:38:10.094+0000] {logging_mixin.py:188} WARNING - /home/***/.local/lib/python3.12/site-packages/***/task/task_runner/standard_task_runner.py:61 DeprecationWarning: This process (pid=35950) is multi-threaded, use of fork() may lead to deadlocks in the child.
[2026-05-05T08:38:10.111+0000] {standard_task_runner.py:63} INFO - Started process 36023 to run task
[2026-05-05T08:38:10.111+0000] {standard_task_runner.py:90} INFO - Running: ['***', 'tasks', 'run', 'deployment_workflow', 'simulate_os_validation_error', 'manual__2026-05-05T08:37:46.600216', '--job-id', '152', '--raw', '--subdir', 'DAGS_FOLDER/deployment_workflow.py', '--cfg-path', '/tmp/tmpjoy7npn3', '--map-index', '0']
[2026-05-05T08:38:10.125+0000] {standard_task_runner.py:91} INFO - Job 152: Subtask simulate_os_validation_error
[2026-05-05T08:38:10.545+0000] {task_command.py:426} INFO - Running <TaskInstance: deployment_workflow.simulate_os_validation_error manual__2026-05-05T08:37:46.600216 map_index=0 [running]> on host 5285e5440265
[2026-05-05T08:38:11.302+0000] {taskinstance.py:2648} INFO - Exporting env vars: AIRFLOW_CTX_DAG_OWNER='***' AIRFLOW_CTX_DAG_ID='deployment_workflow' AIRFLOW_CTX_TASK_ID='simulate_os_validation_error' AIRFLOW_CTX_EXECUTION_DATE='2026-05-05T08:37:47.990735+00:00' AIRFLOW_CTX_TRY_NUMBER='1' AIRFLOW_CTX_DAG_RUN_ID='manual__2026-05-05T08:37:46.600216'
[2026-05-05T08:38:11.340+0000] {taskinstance.py:430} INFO - ::endgroup::
[2026-05-05T08:38:11.343+0000] {ssh.py:151} INFO - Creating ssh_client
[2026-05-05T08:38:11.364+0000] {ssh.py:124} INFO - ssh_hook is not provided or invalid. Trying ssh_conn_id to create SSHHook.
[2026-05-05T08:38:11.406+0000] {base.py:84} INFO - Using connection ID 'worker_node_192_168_1_5' for task execution.
[2026-05-05T08:38:11.413+0000] {ssh.py:301} WARNING - No Host Key Verification. This won't protect against Man-In-The-Middle attacks
[2026-05-05T08:38:11.553+0000] {transport.py:1909} INFO - Connected (version 2.0, client OpenSSH_10.2p1)
[2026-05-05T08:38:12.071+0000] {transport.py:1909} INFO - Authentication (password) successful!
[2026-05-05T08:38:12.076+0000] {ssh.py:480} INFO - Running command: set -e; echo 'Simulating realistic OS validation failure...'; uname -a; id; echo 'Expecting RHEL-style baseline validation on a non-RHEL host...'; test -f /etc/redhat-release || (echo 'OS baseline validation failed: expected /etc/redhat-release on target host' >&2; exit 1)
[2026-05-05T08:38:12.590+0000] {ssh.py:526} INFO - Simulating realistic OS validation failure...
[2026-05-05T08:38:12.614+0000] {ssh.py:526} INFO - Linux *** 6.18.12+***-amd64 #1 SMP PREEMPT_DYNAMIC Kali 6.18.12-1***1 (2026-02-25) x86_64 GNU/Linux
[2026-05-05T08:38:12.639+0000] {ssh.py:526} INFO - uid=1000(***) gid=1000(***) groups=1000(***),4(adm),20(dialout),24(cdrom),25(floppy),27(sudo),29(audio),30(dip),44(video),46(plugdev),100(users),101(netdev),102(scanner),104(bluetooth),113(lpadmin),122(wireshark),123(kaboxer),124(vboxsf)
[2026-05-05T08:38:12.654+0000] {ssh.py:526} INFO - Expecting RHEL-style baseline validation on a non-RHEL host...
[2026-05-05T08:38:12.685+0000] {ssh.py:526} INFO - OS baseline validation failed: expected /etc/redhat-release on target host
[2026-05-05T08:38:12.820+0000] {taskinstance.py:441} INFO - ::group::Post task execution logs
[2026-05-05T08:38:12.895+0000] {taskinstance.py:2905} ERROR - Task failed with exception
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
airflow.exceptions.AirflowException: SSH operator error: exit status = 1
[2026-05-05T08:38:12.938+0000] {taskinstance.py:1206} INFO - Marking task as FAILED. dag_id=deployment_workflow, task_id=simulate_os_validation_error, run_id=manual__2026-05-05T08:37:46.600216, map_index=0, execution_date=20260505T083747, start_date=20260505T083809, end_date=20260505T083812
[2026-05-05T08:38:13.087+0000] {standard_task_runner.py:110} ERROR - Failed to execute job 152 for task simulate_os_validation_error (SSH operator error: exit status = 1; 36023)
[2026-05-05T08:38:13.274+0000] {local_task_job_runner.py:240} INFO - Task exited with return code 1
[2026-05-05T08:38:13.438+0000] {taskinstance.py:3498} INFO - 0 downstream tasks scheduled from follow-on schedule check
[2026-05-05T08:38:13.446+0000] {local_task_job_runner.py:222} INFO - ::endgroup::
"""

# --- INPUT: Set your task_id here ---
TASK_ID = "simulate_os_validation_error"


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
    print(f"Error Location : {result['error_location']}")
    print(f"Error Type     : {result['error_type']}")
    print(f"Error Message  : {result['error_message']}")
    print(f"Sources        : {result['retrieved_sources']}")

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

    print(f"    DAG ID      : {parsed_error.dag_id}")
    print(f"    Task ID     : {parsed_error.task_id}")
    print(f"    Error Type  : {parsed_error.error_type}")
    print(f"    Error Msg   : {parsed_error.error_message}")
    print(f"    File        : {parsed_error.file_path}")
    print(f"    Line No     : {parsed_error.line_number}")

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
