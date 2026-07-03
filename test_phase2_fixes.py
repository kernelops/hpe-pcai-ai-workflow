"""
test_fix_loop.py
Ping-pong test: FixGeneratorAgent ↔ FixExecutorAgent
  - Iteration 1 : get_first_batch → execute_batch
  - Iterations 2-5 : get_next_batch → execute_batch (x4)
"""
from agents.fix_generator_agent import FixGeneratorAgent
from agents.fix_executor_agent import FixExecutorAgent
from common.models import RootCauseReport, ErrorReport

# ── PLACEHOLDERS ────────────────────────────────────────────────────────────

WORKER_NODES = [
    {"ip": "192.168.1.5", "username": "kali", "password": "kali"},
]

MOCK = False  # Set False to run real SSH

ERROR_REPORT = ErrorReport(
    task_id   = "check_minio_health",
    error_type = " ",
    error_message = " ",
    error_line = " ",
    raw_log   = "[2026-06-26T05:34:40.061+0000] {local_task_job_runner.py:120} INFO - ::group::Pre task execution logs\n[2026-06-26T05:34:40.115+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=non-requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [queued]>\n[2026-06-26T05:34:40.139+0000] {taskinstance.py:2076} INFO - Dependencies all met for dep_context=requeueable deps ti=<TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [queued]>\n[2026-06-26T05:34:40.142+0000] {taskinstance.py:2306} INFO - Starting attempt 1 of 1\n[2026-06-26T05:34:40.191+0000] {taskinstance.py:2330} INFO - Executing <Task(SSHOperator): check_minio_health> on 2026-06-26 05:34:30.932255+00:00\n[2026-06-26T05:34:40.222+0000] {warnings.py:110} WARNING - /home/***/.local/lib/python3.12/site-packages/***/task/task_runner/standard_task_runner.py:61: DeprecationWarning: This process (pid=366) is multi-threaded, use of fork() may lead to deadlocks in the child.\n  pid = os.fork()\n\n[2026-06-26T05:34:40.233+0000] {standard_task_runner.py:63} INFO - Started process 368 to run task\n[2026-06-26T05:34:40.230+0000] {standard_task_runner.py:90} INFO - Running: [\'***\', \'tasks\', \'run\', \'minio_health_check\', \'check_minio_health\', \'manual__2026-06-26T05:34:29.072153\', \'--job-id\', \'379\', \'--raw\', \'--subdir\', \'DAGS_FOLDER/minio_healthcheck_dag.py\', \'--cfg-path\', \'/tmp/tmpp4sas9eq\']\n[2026-06-26T05:34:40.238+0000] {standard_task_runner.py:91} INFO - Job 379: Subtask check_minio_health\n[2026-06-26T05:34:40.399+0000] {task_command.py:426} INFO - Running <TaskInstance: minio_health_check.check_minio_health manual__2026-06-26T05:34:29.072153 [running]> on host db2db0122602\n[2026-06-26T05:34:40.630+0000] {taskinstance.py:2648} INFO - Exporting env vars: AIRFLOW_CTX_DAG_OWNER=\'***\' AIRFLOW_CTX_DAG_ID=\'minio_health_check\' AIRFLOW_CTX_TASK_ID=\'check_minio_health\' AIRFLOW_CTX_EXECUTION_DATE=\'2026-06-26T05:34:30.932255+00:00\' AIRFLOW_CTX_TRY_NUMBER=\'1\' AIRFLOW_CTX_DAG_RUN_ID=\'manual__2026-06-26T05:34:29.072153\'\n[2026-06-26T05:34:40.637+0000] {taskinstance.py:430} INFO - ::endgroup::\n[2026-06-26T05:34:40.640+0000] {ssh.py:151} INFO - Creating ssh_client\n[2026-06-26T05:34:40.642+0000] {ssh.py:124} INFO - ssh_hook is not provided or invalid. Trying ssh_conn_id to create SSHHook.\n[2026-06-26T05:34:40.664+0000] {base.py:84} INFO - Using connection ID \'worker_node_192_168_1_5\' for task execution.\n[2026-06-26T05:34:40.668+0000] {ssh.py:301} WARNING - No Host Key Verification. This won\'t protect against Man-In-The-Middle attacks\n[2026-06-26T05:34:40.705+0000] {transport.py:1909} INFO - Connected (version 2.0, client OpenSSH_10.2p1)\n[2026-06-26T05:34:40.965+0000] {transport.py:1909} INFO - Authentication (password) successful!\n[2026-06-26T05:34:40.971+0000] {ssh.py:480} INFO - Running command: curl -f http://localhost:9000/minio/health/live\n[2026-06-26T05:34:41.148+0000] {ssh.py:526} INFO - curl: (7) Failed to connect to localhost port 9000 after 2 ms: Could not connect to server\n[2026-06-26T05:34:41.193+0000] {taskinstance.py:441} INFO - ::group::Post task execution logs\n[2026-06-26T05:34:41.225+0000] {taskinstance.py:2905} ERROR - Task failed with exception\nTraceback (most recent call last):\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py\", line 465, in _execute_task\n    result = _execute_callable(context=context, **execute_callable_kwargs)\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/models/taskinstance.py\", line 432, in _execute_callable\n    return execute_callable(context=context, **execute_callable_kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/models/baseoperator.py\", line 400, in wrapper\n    return func(self, *args, **kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py\", line 191, in execute\n    result = self.run_ssh_client_command(ssh_client, self.command, context=context)\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py\", line 179, in run_ssh_client_command\n    self.raise_for_status(exit_status, agg_stderr, context=context)\n  File \"/home/airflow/.local/lib/python3.12/site-packages/airflow/providers/ssh/operators/ssh.py\", line 173, in raise_for_status\n    raise AirflowException(f\"SSH operator error: exit status = {exit_status}\")\nairflow.exceptions.AirflowException: SSH operator error: exit status = 7\n[2026-06-26T05:34:41.240+0000] {taskinstance.py:1206} INFO - Marking task as FAILED. dag_id=minio_health_check, task_id=check_minio_health, run_id=manual__2026-06-26T05:34:29.072153, execution_date=20260626T053430, start_date=20260626T053440, end_date=20260626T053441\n[2026-06-26T05:34:41.281+0000] {standard_task_runner.py:110} ERROR - Failed to execute job 379 for task check_minio_health (SSH operator error: exit status = 7; 368)\n[2026-06-26T05:34:41.342+0000] {local_task_job_runner.py:240} INFO - Task exited with return code 1\n[2026-06-26T05:34:41.404+0000] {taskinstance.py:3498} INFO - 0 downstream tasks scheduled from follow-on schedule check\n[2026-06-26T05:34:41.417+0000] {local_task_job_runner.py:222} INFO - ::endgroup::",
    diagnosis = "The task failed due to an SSH operator error, which occurred when the curl command to check MinIO health failed to connect to localhost port 9000. This suggests a potential issue with the MinIO service or the network connection.",
    confidence = 0.9,
    rag_error_location = None,
    rag_diagnosis = None,
    rag_solution = None,
    rag_prevention = None,
    rag_sources = [],
)

RCA = RootCauseReport(
    error_report    = ERROR_REPORT,
    root_cause      = "The MinIO service is not running or not listening on port 9000, causing the SSH operator error.",
    classification = "",
    severity = "",
    engineer_action = "Verify the MinIO service status and configuration, and restart the service if necessary to ensure it is listening on port 9000",
)

COMMAND_THAT_FAILED = "f\"curl -f http://localhost:9000/minio/health/live"

# ── TEST ─────────────────────────────────────────────────────────────────────

def run():
    gen  = FixGeneratorAgent()
    exec = FixExecutorAgent()

    command_history: list[dict] = []

    # ── Iteration 1: Prompt 1 → execute ──────────────────────────────────────
    print("\n" + "="*60)
    print("ITERATION 1 — get_first_batch → execute_batch")
    print("="*60)

    batch = gen.get_first_batch(RCA)
    phase = batch.get("phase", "diagnostic")
    cmds  = batch.get("next_commands", [])
    print(f"Phase     : {phase}")
    print(f"Commands  : {cmds}")

    results = exec.execute_batch(cmds, WORKER_NODES, phase=phase, mock=MOCK)
    command_history.extend(results)

    # ── Iterations 2-5: Prompt 2 → execute ───────────────────────────────────
    for i in range(2, 6):
        print("\n" + "="*60)
        print(f"ITERATION {i} — get_next_batch → execute_batch")
        print("="*60)

        batch = gen.get_next_batch(RCA, command_history, COMMAND_THAT_FAILED)
        phase = batch.get("phase", "unknown")
        cmds  = batch.get("next_commands", [])
        print(f"Phase     : {phase}")
        print(f"Commands  : {cmds}")

        if phase == "done" or not cmds:
            print("→ LLM signalled done. Stopping early.")
            break

        results = exec.execute_batch(cmds, WORKER_NODES, phase=phase, mock=MOCK)
        command_history.extend(results)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"DONE — {len(command_history)} total commands executed")
    for e in command_history:
        status = "✓" if e["exit_code"] == 0 else "✗"
        print(f"  {status} [{e['phase']}] {e['command'][:80]}")

if __name__ == "__main__":
    run()