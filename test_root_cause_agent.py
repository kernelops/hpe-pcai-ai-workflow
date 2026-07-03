"""
test_root_cause_agent.py

Standalone test for RootCauseAgent.
Builds an ErrorReport manually and passes it to analyse().

Run with: python test_root_cause_agent.py
"""
from agents.root_cause_agent import RootCauseAgent
from common.models import ErrorReport

# --- From LLM (log analyser output) ---
TASK_ID             = "check_minio_health"
ERROR_TYPE          = "NetworkError"
ERROR_MESSAGE       = "SSH operator error: exit status = 7"
ERROR_LINE          = "/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py:173"
DIAGNOSIS           = "The curl command failed to connect to localhost port 9000, likely due to the target service not running or a network/firewall restriction. The MinIO health check service is not reachable"
CONFIDENCE          = 0.9
COMMAND_THAT_FAILED = "curl -f http://localhost:9000/minio/health/live"
RAG_ERROR_LOCATION  = "DAG: minio_health_check | Task: check_minio_health | File: /home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py | Line: 173 | Error Type: AirflowException"

RAG_DIAGNOSIS = """
log-line = AirflowException: SSH operator error: exit status = 7
The command executed but failed with exit code 7. For curl commands, exit code 7 specifically indicates a failure to connect to the host (connection refused, host unreachable, or timeout). For other commands, exit code 7 may have different meanings depending on the application. Likely causes could be target service not running, wrong host or port, port is closed or not listening, or network/firewall restrictions.\n\n
log-line = curl: (7) Failed to connect to localhost port 9000 after 2 ms: Could not connect to server
The curl command failed because it could not establish a TCP connection to the specified host and port. The connection was actively refused by the target machine, indicating that no service is listening on the specified host and port, or a firewall is rejecting the connection. Likely causes are target service is not running, service is running on a different port, service crashed or exited, port is not exposed, or firewall rules are blocking the port.
"""

RAG_SOLUTION = """
log-line = AirflowException: SSH operator error: exit status = 7
Identify which command failed (history | tail -n 5). If using curl, retry with verbose output (curl -v http://<HOST>:<PORT>). Check if service is running (ss -tuln | grep <PORT>). Check connectivity to confirm network reachability (ping <HOST>). If using Docker, ensure container is running and check port mapping.\n\n
log-line = curl: (7) Failed to connect to localhost port 9000 after 2 ms: Could not connect to server
Check if any service is listening on the port (ss -tuln | grep <PORT>). If nothing shows, no service is running on that port. Check whether the required service is running (ps aux | grep <SERVICE_NAME>). Start the service if not running. Verify that the service is configured to run on the expected port (cat config.yaml). If using Docker, confirm that the container is running and check port mapping.
"""

RAG_PREVENTION = """
log-line = AirflowException: SSH operator error: exit status = 7
Verify service before connecting. Use correct host and port. Confirm server readiness before requests.
log-line = curl: (7) Failed to connect to localhost port 9000 after 2 ms: Could not connect to server
Always verify service is running before connecting; avoid blind curl requests. Use health checks to confirm service availability.
"""
RAG_SOURCES     = ["OS Validation Logs"]

RAW_LOG = """
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
[2026-06-26T05:34:41.417+0000] {local_task_job_runner.py:222} INFO - ::endgroup::
"""

def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

if __name__ == "__main__":
    print("\n[*] Building ErrorReport...")

    error_report = ErrorReport(
        task_id             = TASK_ID,
        error_type          = ERROR_TYPE,
        error_message       = ERROR_MESSAGE,
        error_line          = ERROR_LINE,
        diagnosis           = DIAGNOSIS,
        confidence          = CONFIDENCE,
        raw_log             = RAW_LOG.strip(),
        command_that_failed = COMMAND_THAT_FAILED,
        rag_error_location  = RAG_ERROR_LOCATION,
        rag_diagnosis       = RAG_DIAGNOSIS,
        rag_solution        = RAG_SOLUTION,
        rag_prevention      = RAG_PREVENTION,
        rag_sources         = RAG_SOURCES,
    )

    print("\n[*] Running RootCauseAgent.analyse()...")
    agent  = RootCauseAgent()
    report = agent.analyse(error_report)

    print("\nFinal RCA Report from test file:", report)