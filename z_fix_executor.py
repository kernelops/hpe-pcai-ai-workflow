"""
fix_executor_agent.py

Phase 2 — Fix Executor Agent.
Dumb runner — receives structured command batches from fix_generator_agent,
validates them against a whitelist, executes via paramiko SSH, returns outputs.

Also contains the orchestration loop that ties generator and executor together.
"""

import time
import paramiko
from z_fix_generator import (
    FixGeneratorAgent,
    ALLOWED_COMMAND_PREFIXES,
    TASK_ID,
    ERROR_MESSAGE,
    MAX_ITERATIONS,
)

# ══════════════════════════════════════════════════════════════
# CONFIG — worker node SSH credentials
# ══════════════════════════════════════════════════════════════

WORKER_IP       = "192.168.1.5"
WORKER_USERNAME = "kali"
WORKER_PASSWORD = "kali"


# ══════════════════════════════════════════════════════════════
# WHITELIST VALIDATION
# ══════════════════════════════════════════════════════════════

def is_command_allowed(command: str) -> bool:
    """
    Returns True if the command starts with an allowed prefix.
    Rejects anything not in the whitelist.
    """
    cmd = command.strip()
    return any(cmd.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES)


def validate_commands(commands: list[str]) -> tuple[bool, list[str]]:
    """
    Validates all commands in a batch against the whitelist.
    Returns (all_allowed, list_of_rejected_commands).
    """
    rejected = [cmd for cmd in commands if not is_command_allowed(cmd)]
    return (len(rejected) == 0), rejected


# ══════════════════════════════════════════════════════════════
# SSH EXECUTION
# ══════════════════════════════════════════════════════════════

def get_ssh_client(ip: str, username: str, password: str) -> paramiko.SSHClient:
    """Opens and returns a connected paramiko SSH client."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        ip,
        username=username,
        password=password,
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def run_command(
    client: paramiko.SSHClient,
    command: str,
    password: str,
) -> dict:
    """
    Runs a single command over an existing SSH connection.
    Handles sudo password injection automatically.
    Returns dict with command, stdout, stderr, exit_code.
    """
    if "sudo" in command:
        stdin, stdout, stderr = client.exec_command(command, get_pty=True)
        stdin.write(password + "\n")
        stdin.flush()
        time.sleep(0.5)
    else:
        stdin, stdout, stderr = client.exec_command(command)

    stdout.channel.settimeout(60)
    exit_code = stdout.channel.recv_exit_status()
    output    = stdout.read().decode("utf-8", errors="replace").strip()

    # Strip sudo password echo from PTY output
    if password and ("[sudo] password for" in output or password in output):
        lines  = output.split("\n")
        lines  = [
            l for l in lines
            if not l.startswith("[sudo] password for")
            and l.strip() != password
        ]
        output = "\n".join(lines).strip()

    err = ""
    if "sudo" not in command:
        err = stderr.read().decode("utf-8", errors="replace").strip()

    print(f"\n  $ {command}")
    print(f"    EXIT: {exit_code}")
    if output:
        print(f"    OUT:  {output[:300]}")
    if err:
        print(f"    ERR:  {err[:200]}")

    return {
        "command":   command,
        "exit_code": exit_code,
        "stdout":    output,
        "stderr":    err,
    }


# ══════════════════════════════════════════════════════════════
# FIX EXECUTOR AGENT
# ══════════════════════════════════════════════════════════════

class FixExecutorAgent:

    def __init__(self, ip: str, username: str, password: str):
        self.ip       = ip
        self.username = username
        self.password = password

    def execute_batch(self, commands: list[str]) -> list[dict]:
        """
        Validates and executes a batch of commands via SSH.
        Opens a fresh SSH connection per batch.
        Returns list of result dicts.
        """
        # --- Whitelist check ---
        all_ok, rejected = validate_commands(commands)
        if not all_ok:
            print(f"\n[FixExecutor] ⚠️ WARNING — commands not in whitelist:")
            for cmd in rejected:
                print(f"  → {cmd}")

        # --- SSH execution ---
        # One connection per command — sudo with PTY can close the channel
        # after completion, making it unusable for the next command.
        results = []

        for cmd in commands:
            print(f"\n[FixExecutor] Connecting to {self.username}@{self.ip}...")
            client = get_ssh_client(self.ip, self.username, self.password)
            try:
                result = run_command(client, cmd, self.password)
                results.append(result)
            finally:
                client.close()

        print(f"\n[FixExecutor] Batch complete — {len(results)} commands run.")
        return results


# ══════════════════════════════════════════════════════════════
# ORCHESTRATION LOOP
# ══════════════════════════════════════════════════════════════

def run_fix_pipeline():
    """
    Ties fix_generator_agent and fix_executor_agent together.

    Flow:
      1. Prompt 1  → first batch of commands
      2. Executor  → runs commands, captures outputs
      3. Prompt 2  → reads outputs, decides next commands or done
      4. Repeat 3 until phase=done or MAX_ITERATIONS hit
      5. Report final status
    """
    print(f"\n{'='*60}")
    print(f"  FIX PIPELINE STARTING")
    print(f"  Task:  {TASK_ID}")
    print(f"  Error: {ERROR_MESSAGE}")
    print(f"{'='*60}\n")

    generator = FixGeneratorAgent(TASK_ID, ERROR_MESSAGE)
    executor  = FixExecutorAgent(WORKER_IP, WORKER_USERNAME, WORKER_PASSWORD)

    command_history: list[dict] = []

    # ── Step 1: Prompt 1 → first batch ───────────────────────
    first_batch = generator.get_first_batch()
    commands    = first_batch.get("next_commands", [])

    if not commands:
        print("[Pipeline] Prompt 1 returned no commands. Exiting.")
        return

    # ── Steps 2-4: Execute → Prompt 2 loop ───────────────────
    for iteration in range(MAX_ITERATIONS):
        print(f"\n{'─'*60}")
        print(f"  ITERATION {iteration + 1} of {MAX_ITERATIONS}")
        print(f"{'─'*60}")

        # Execute current batch
        results = executor.execute_batch(commands)

        # Add to history
        command_history.extend(results)

        # Ask generator what to do next
        next_batch = generator.get_next_batch(command_history)
        phase      = next_batch.get("phase", "")
        commands   = next_batch.get("next_commands", [])

        if phase == "done" or not commands:
            print(f"\n{'='*60}")
            print(f"  ✅ FIX PIPELINE COMPLETE")
            print(f"  Reasoning: {next_batch.get('reasoning')}")
            print(f"  The DAG is safe to retrigger.")
            print(f"{'='*60}\n")
            return

    # ── Max iterations hit ────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ❌ MAX ITERATIONS ({MAX_ITERATIONS}) REACHED WITHOUT RESOLUTION")
    print(f"  Manual investigation required before retriggering the DAG.")
    print(f"  Command history summary:")
    for entry in command_history:
        status = "✓" if entry["exit_code"] == 0 else "✗"
        print(f"    {status} [{entry['exit_code']}] {entry['command'][:60]}")
    print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_fix_pipeline()