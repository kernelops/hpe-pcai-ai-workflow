"""
fix_executor_agent.py
Phase 2 — Fix Executor Agent.

New RAG-based architecture:
  execute_rag_diagnostics() → Calls RAG, executes all diagnostic commands
  execute_rag_fix() → Executes specific fix commands for a selected reason
"""

import time
import json
from datetime import datetime
from common.models import FixStrategy, FixResult
from agents.fix_generator_agent import ALLOWED_COMMAND_PREFIXES
import socket
import requests  # Add this with other imports


class FixExecutorAgent:
    """
    Executes command batches on remote worker nodes via SSH.
    Now supports RAG-based diagnostic and fix execution.
    """

    def __init__(self, rag_api_url: str = "http://localhost:8002"):
        self._paramiko = None   # lazy-load
        self.max_retries = 3
        self.retry_delay = 2
        self.rag_api_url = rag_api_url  # Add this


    def execute_rag_diagnostics(
        self,
        task_id: str,
        raw_log: str,
        worker_nodes: list[dict],
        mock: bool = False,
    ) -> tuple[dict, list[dict]]:
        """
        Executes RAG-based diagnostics.
        Returns:
            (rag_entry, diagnostic_results)
            
            rag_entry: The matched RAG entry with fix_possibilities, fix_commands, etc.
            diagnostic_results: Results from executing all diagnostic commands
        """
        task_id = task_id.split("/map_index=")[0]
        print(f"\n[FixExecutor]  RAG Diagnostics — Task: {task_id}")
        
        # Step 1: Call RAG API
        try:
            r = requests.post(
                f"{self.rag_api_url}/retrieve-fix",
                json={
                    "task_id": task_id,
                    "raw_log": raw_log,
                },
                timeout=30
            )
            if r.status_code == 200:
                data = r.json()
                results = data.get("matches", [])
                print(f"[FixExecutor] ✅ RAG API returned {data.get('count', 0)} matches")
            else:
                print(f"[FixExecutor] RAG API error: {r.status_code} {r.text}")
                return {}, []
        except Exception as e:
            print(f"[FixExecutor] RAG API call failed: {e}")
            return {}, []

        if not results:
            print("[FixExecutor] No RAG match found")
            return {}, []
        
        # Take the best match (first one)
        rag_entry = results[0]
        print(f"[FixExecutor] ✅ RAG match found: {rag_entry.get('task_id')}")
        print(f"[FixExecutor]    Similarity: {rag_entry.get('similarity')}")
        
        # Step 2: Extract diagnostic commands
        diagnostic_commands = rag_entry.get("diagnostic_commands", [])
        if not diagnostic_commands:
            print("[FixExecutor] ⚠️  No diagnostic commands in RAG entry")
            return rag_entry, []
        
        # Flatten the nested lists
        flat_commands = []
        for cmd_group in diagnostic_commands:
            if isinstance(cmd_group, list):
                flat_commands.extend(cmd_group)
            else:
                flat_commands.append(str(cmd_group))
        
        print(f"[FixExecutor] Executing {len(flat_commands)} diagnostic commands...")
        
        # Step 3: Execute all diagnostic commands
        results = self.execute_batch(
            commands=flat_commands,
            worker_nodes=worker_nodes,
            phase="diagnostic",
            mock=mock
        )
        
        print(f"[FixExecutor] Diagnostic execution complete: {len(results)} results")
        
        return rag_entry, results

    def execute_rag_fix(
        self,
        rag_entry: dict,
        selected_index: int,
        worker_nodes: list[dict],
        mock: bool = False
    ) -> list[dict]:
        """
        Executes fix commands for a specific selected index.
        
        Args:
            rag_entry: The RAG entry with fix_commands
            selected_index: Index of which fix_possibility to execute
            worker_nodes: Nodes to run commands on
        
        Returns:
            List of execution results
        """
        print(f"\n[FixExecutor]  RAG Fix — Selected Index: {selected_index}")
        
        # Step 1: Get fix_commands from rag_entry
        fix_commands_dict = rag_entry.get("fix_commands", {})
        
        # Get the fix possibilities list to map index to key
        fix_possibilities = rag_entry.get("fix_possibilities", [])
        
        if selected_index >= len(fix_possibilities):
            print(f"[FixExecutor] ❌ Invalid index: {selected_index} (max: {len(fix_possibilities)-1})")
            return []
        
        # Get the fix reason key
        fix_reason = fix_possibilities[selected_index]
        print(f"[FixExecutor]  Fix reason: {fix_reason}")
        
        # Get commands for this reason
        fix_commands = fix_commands_dict.get(fix_reason, [])
        
        if not fix_commands:
            print(f"[FixExecutor] ⚠️  No fix commands for reason: {fix_reason}")
            return []
        
        print(f"[FixExecutor]  Executing {len(fix_commands)} fix commands...")
        
        # Step 2: Execute fix commands
        results = self.execute_batch(
            commands=fix_commands,
            worker_nodes=worker_nodes,
            phase="fix",
            mock=mock
        )
        
        print(f"[FixExecutor] ✅ Fix execution complete: {len(results)} results")
        
        return results

    def execute_batch(
        self,
        commands: list[str],
        worker_nodes: list[dict],
        phase: str = "unknown",
        mock: bool = False,
    ) -> list[dict]:
        """Execute a batch of commands (unchanged)."""
        if not commands:
            return []

        if mock:
            targets = worker_nodes or [{"ip": "mock-node", "username": "root", "password": ""}]
            results = []
            for node in targets:
                for cmd in commands:
                    print(f"\n  [MOCK] $ {cmd}")
                    results.append({
                        "command"   : cmd,
                        "node_ip"   : node["ip"],
                        "stdout"    : f"[MOCK] OK: {cmd}",
                        "stderr"    : "",
                        "exit_code" : 0,
                        "phase"     : phase,
                        "timestamp" : datetime.now().isoformat(),
                    })
            return results

        if not worker_nodes:
            print("[FixExecutor] ⚠️  No worker nodes — skipping execution")
            return []

        results = []
        for node in worker_nodes:
            ip       = node["ip"]
            username = node["username"]
            password = node.get("password", "")

            print(f"\n[FixExecutor]  Node: {ip}  Phase: {phase}")

            for cmd in commands:
                paramiko = self._get_paramiko()
                client   = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                result = {
                    "command"   : cmd,
                    "node_ip"   : ip,
                    "stdout"    : "",
                    "stderr"    : "",
                    "exit_code" : 0,
                    "phase"     : phase,
                    "timestamp" : datetime.now().isoformat(),
                }

                try:
                    client.connect(
                        hostname     = ip,
                        username     = username,
                        password     = password,
                        timeout      = 5,
                        look_for_keys= False,
                        allow_agent  = False,
                    )

                    if "sudo" in cmd:
                        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                
                    else:
                        stdin, stdout, stderr = client.exec_command(cmd)

                    stdout.channel.settimeout(60)

                    if "sudo" in cmd and password:
                        stdin.write(password + "\n")
                        stdin.flush()
                        time.sleep(0.5)

                    result["exit_code"] = stdout.channel.recv_exit_status()
                    output = stdout.read().decode("utf-8", errors="replace").strip()
                    output = output.replace(password, "")

                    if password and (
                        "[sudo] password for" in output or password in output
                    ):
                        lines  = output.split("\n")
                        lines  = [
                            l for l in lines
                            if not l.startswith("[sudo] password for")
                            and l.strip() != password
                        ]
                        output = "\n".join(lines).strip()

                    result["stdout"] = output
                    result["stderr"] = (
                        "" if "sudo" in cmd
                        else stderr.read().decode()
                    )

                except Exception as exc:
                    result["exit_code"] = -1
                    result["stderr"]    = f"SSH error: {str(exc)}"

                finally:
                    client.close()

                print(f"[{result['exit_code']}] $ {cmd}")
                if result["stdout"]:
                    print(f"    OUT: {result['stdout'][:300]}")
                if result["stderr"]:
                    print(f"    ERR: {result['stderr'][:200]}")

                results.append(result)

        return results

    def build_fix_result(
        self,
        strategy: FixStrategy,
        command_history: list[dict],
    ) -> FixResult:
        """Build fix result (unchanged)."""
        fix_phase_outputs = [
            e for e in command_history
            if e.get("phase") in ("fix", "verification", "unknown")
        ]

        any_failure = any(
            e.get("exit_code", 0) != 0
            for e in fix_phase_outputs
        )

        status    = "failed" if any_failure else "success"
        error_msg = None

        if any_failure:
            first_fail = next(
                (e for e in fix_phase_outputs if e.get("exit_code", 0) != 0),
                None,
            )
            if first_fail:
                error_msg = (
                    f"Command failed: {first_fail['command'][:80]} "
                    f"— {first_fail.get('stderr', '')[:200]}"
                )

        print(
            f"\n[FixExecutor] {'✅' if not any_failure else '❌'} "
            f"Loop complete — {status.upper()} "
            f"({len(command_history)} total commands)"
        )

        return FixResult(
            fix_strategy     = strategy,
            execution_status = status,
            command_outputs  = command_history,
            error_on_fix     = error_msg,
        )

    def execute(
        self,
        strategy: FixStrategy,
        worker_nodes: list[dict],
        approved: bool = False,
        mock: bool = False,
    ) -> FixResult:
        """Legacy execute (unchanged)."""
        print(f"[FixExecutor] 🔧 Legacy execute: {strategy.description}")

        if strategy.requires_approval and not approved:
            print("[FixExecutor] ⏳ Requires approval — returning pending")
            return FixResult(
                fix_strategy     = strategy,
                execution_status = "pending_approval",
            )

        targets = worker_nodes
        if not targets and mock:
            targets = [{"ip": "mock-node", "username": "root", "password": ""}]

        if not targets:
            return FixResult(
                fix_strategy     = strategy,
                execution_status = "skipped",
                error_on_fix     = "No target worker nodes available",
            )

        history = []
        history += self.execute_batch(
            strategy.dry_run_commands, targets, phase="diagnostic", mock=mock
        )
        history += self.execute_batch(
            strategy.fix_commands, targets, phase="fix", mock=mock
        )

        return self.build_fix_result(strategy, history)

    def _validate_commands(
        self, commands: list[str]
    ) -> tuple[bool, list[str]]:
        rejected = [
            cmd for cmd in commands
            if not any(
                cmd.strip().startswith(prefix)
                for prefix in ALLOWED_COMMAND_PREFIXES
            )
        ]
        return (len(rejected) == 0), rejected

    def _get_paramiko(self):
        if self._paramiko is None:
            try:
                import paramiko
                self._paramiko = paramiko
            except ImportError:
                raise ImportError(
                    "paramiko is required. Install with: pip install paramiko"
                )
        return self._paramiko