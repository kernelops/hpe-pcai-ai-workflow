# agents/fix_executor_agent.py
"""
Phase 2 — Fix Executor Agent.
Takes a FixStrategy and executes the fix commands on worker
nodes via SSH (using paramiko).

Supports:
- Dry-run verification before applying fixes
- Human-approval gating (returns pending status if approval needed)
- Per-command output capture (stdout, stderr, exit code)
- Mock execution for testing without real SSH targets
"""

import time
from datetime import datetime
from common.models import FixStrategy, FixResult


class FixExecutorAgent:
    """
    Executes fix commands on remote worker nodes via SSH.
    """

    def __init__(self):
        self._paramiko = None  # lazy-load paramiko

    # ── Public entry point ────────────────────────────────────

    def execute(
        self,
        strategy: FixStrategy,
        worker_nodes: list[dict],
        approved: bool = False,
        mock: bool = False,
    ) -> FixResult:
        """
        Execute a fix strategy.

        Args:
            strategy:     The fix plan to execute.
            worker_nodes: List of dicts with ip/username/password.
            approved:     Whether human has approved (skip if requires_approval is False).
            mock:         If True, simulate execution without SSH.
        """
        print(f"[FixExecutor] 🔧 Executing fix: {strategy.description}")

        # Gate on approval
        if strategy.requires_approval and not approved:
            print("[FixExecutor] ⏳ Fix requires approval — returning pending")
            return FixResult(
                fix_strategy=strategy,
                execution_status="pending_approval",
            )

        # Determine target nodes
        targets = self._resolve_targets(strategy, worker_nodes)

        # In mock mode, use a dummy node if none are provided
        if not targets and mock:
            print("[FixExecutor] 📋 No worker nodes — using mock target node")
            targets = [{"ip": "mock-node", "username": "root", "password": ""}]

        if not targets:
            print("[FixExecutor] ⚠️  No target nodes found — skipping fix")
            return FixResult(
                fix_strategy=strategy,
                execution_status="skipped",
                error_on_fix="No target worker nodes available",
            )

        all_outputs: list[dict] = []
        any_failure = False

        for node in targets:
            ip = node["ip"]
            username = node["username"]
            password = node.get("password", "")

            print(f"\n[FixExecutor] 🖥  Node: {ip}")

            # 1. Run dry-run commands
            if strategy.dry_run_commands:
                print("[FixExecutor]   ── Dry-run verification ──")
                for cmd in strategy.dry_run_commands:
                    output = self._run_command(ip, username, password, cmd, mock=mock)
                    output["phase"] = "dry_run"
                    all_outputs.append(output)
                    print(f"  $ {cmd}")
                    if output["stdout"]:
                        print(f"    → {output['stdout'][:200]}")

            # 2. Run fix commands
            print("[FixExecutor]   ── Applying fix ──")
            for cmd in strategy.fix_commands:
                output = self._run_command(ip, username, password, cmd, mock=mock)
                output["phase"] = "fix"
                all_outputs.append(output)
                print(f"  $ {cmd}")
                if output["stdout"]:
                    print(f"    → {output['stdout'][:200]}")
                if output["exit_code"] != 0:
                    print(f"    ✗ Exit code: {output['exit_code']}")
                    print(f"    ✗ Stderr: {output['stderr'][:200]}")
                    any_failure = True
                else:
                    print(f"    ✓ OK")

        status = "failed" if any_failure else "success"
        error_msg = None
        if any_failure:
            failed_cmds = [o for o in all_outputs if o.get("exit_code", 0) != 0 and o.get("phase") == "fix"]
            if failed_cmds:
                error_msg = f"Command failed: {failed_cmds[0].get('command', '?')} — {failed_cmds[0].get('stderr', '')[:200]}"

        print(f"\n[FixExecutor] {'✅' if not any_failure else '❌'} "
              f"Fix execution: {status.upper()}")

        return FixResult(
            fix_strategy=strategy,
            execution_status=status,
            command_outputs=all_outputs,
            error_on_fix=error_msg,
        )

    # ── Target resolution ─────────────────────────────────────

    def _resolve_targets(
        self, strategy: FixStrategy, worker_nodes: list[dict]
    ) -> list[dict]:
        """
        If strategy specifies a target IP, filter to that node.
        Otherwise, run on all worker nodes.
        """
        if strategy.target_node_ip:
            return [n for n in worker_nodes if n.get("ip") == strategy.target_node_ip]
        return list(worker_nodes)

    # ── Command execution ─────────────────────────────────────

    def _run_command(
        self,
        ip: str,
        username: str,
        password: str,
        command: str,
        mock: bool = False,
    ) -> dict:
        """
        Execute a single command on a remote host via SSH.
        Returns dict with command, stdout, stderr, exit_code, node_ip.
        """
        result = {
            "command": command,
            "node_ip": ip,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "timestamp": datetime.now().isoformat(),
        }

        if mock:
            result["stdout"] = f"[MOCK] Command executed successfully: {command}"
            return result

        try:
            paramiko = self._get_paramiko()
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=ip,
                username=username,
                password=password,
                timeout=15,
                look_for_keys=False,
                allow_agent=False,
            )

            kwargs = {"timeout": 60}
            if "sudo" in command:
                kwargs["get_pty"] = True

            # Use get_transport for command execution with timeout
            stdin, stdout, stderr = client.exec_command(command, **kwargs)

            if "sudo" in command and password:
                stdin.write(password + "\n")
                stdin.flush()
                time.sleep(0.5)

            result["exit_code"] = stdout.channel.recv_exit_status()
            
            output = stdout.read().decode("utf-8", errors="replace").strip()
            
            # Clean up the sudo prompt from the captured output
            if "[sudo] password for" in output:
                lines = output.split("\n")
                lines = [l for l in lines if not l.startswith("[sudo] password for") and not l.strip().endswith(password)]
                output = "\n".join(lines).strip()
                
            result["stdout"] = output
            if not kwargs.get("get_pty"):
                result["stderr"] = stderr.read().decode("utf-8", errors="replace").strip()
            else:
                result["stderr"] = ""

            client.close()
        except Exception as exc:
            result["exit_code"] = -1
            result["stderr"] = f"SSH error: {str(exc)}"

        return result

    # ── Lazy-load paramiko ────────────────────────────────────

    def _get_paramiko(self):
        if self._paramiko is None:
            try:
                import paramiko
                self._paramiko = paramiko
            except ImportError:
                raise ImportError(
                    "paramiko is required for SSH fix execution. "
                    "Install it with: pip install paramiko"
                )
        return self._paramiko
