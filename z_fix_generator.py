"""
fix_generator_agent.py

Phase 2 — Fix Generator Agent.
Uses a two-prompt architecture:
  Prompt 1 (once)  — analyses error + FIX_REGISTRY + root cause → first diagnostic batch
  Prompt 2 (loop)  — reads command outputs → decides next commands or done

FIX_REGISTRY simulates RAG for now. Replace with actual RAG later.
"""

import json
import requests
import os

# ══════════════════════════════════════════════════════════════
# CONFIG — fill these in before running
# ══════════════════════════════════════════════════════════════

TASK_ID       = "check_minio_health"
ERROR_MESSAGE = "curl: (7) Failed to connect to localhost port 9000: Connection refused"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL         = "poolside/laguna-m.1:free"
MAX_ITERATIONS = 5   # safety limit on the verification loop

# ══════════════════════════════════════════════════════════════
# FIX REGISTRY — simulates RAG, replace with ChromaDB later
# ══════════════════════════════════════════════════════════════

FIX_REGISTRY = {
    "check_minio_health": {
        "error_message": "curl: (7) Failed to connect to localhost port 9000: Connection refused",
        "known_causes": [
            "1. MinIO binary was never installed on the node",
            "2. MinIO is installed but the process is not running (crashed or never started)",
            "3. MinIO is running but listening on a different port (not 9000)",
            "4. MinIO is running on port 9000 but bound to 127.0.0.1 only, not 0.0.0.0",
            "5. Firewall (ufw or iptables) is blocking port 9000",
        ],
        "diagnostic_commands": [
            "which minio",
            "which mc",
            "ps aux | grep -v grep | grep minio",
            "sudo systemctl is-active minio",
            "sudo systemctl status minio --no-pager",
            "ss -tuln | grep 9000",
            "ss -tuln | grep -E '900[0-9]'",
            "sudo ufw status",
            "sudo iptables -L INPUT -n | grep 9000",
            "curl -sf http://localhost:9000/minio/health/live && echo HEALTHY || echo UNREACHABLE",
        ],
        "fix_commands": {
            "cause_1_not_installed": [
                "wget https://dl.min.io/server/minio/release/linux-amd64/minio -O /tmp/minio",
                "chmod +x /tmp/minio",
                "sudo mv /tmp/minio /usr/local/bin/minio",
                "sudo useradd -r minio-user -s /sbin/nologin || true",
                "sudo mkdir -p /data/minio",
                "sudo chown -R minio-user:minio-user /data/minio",
                (
                    "sudo tee /etc/systemd/system/minio.service > /dev/null <<'EOF'\n"
                    "[Unit]\n"
                    "Description=MinIO Object Storage\n"
                    "After=network.target\n\n"
                    "[Service]\n"
                    "User=minio-user\n"
                    "Group=minio-user\n"
                    "ExecStart=/usr/local/bin/minio server /data/minio "
                    "--address 0.0.0.0:9000 --console-address 0.0.0.0:9001\n"
                    "Restart=always\n"
                    "RestartSec=5\n"
                    "Environment=MINIO_ROOT_USER=minioadmin\n"
                    "Environment=MINIO_ROOT_PASSWORD=minioadmin\n\n"
                    "[Install]\n"
                    "WantedBy=multi-user.target\n"
                    "EOF"
                ),
                "sudo systemctl daemon-reload",
                "sudo systemctl enable minio",
                "sudo systemctl start minio",
            ],
            "cause_2_not_running": [
                "sudo systemctl start minio",
                "sudo journalctl -u minio -n 20 --no-pager",
            ],
            "cause_3_wrong_port": [
                "sudo systemctl stop minio",
                (
                    "sudo sed -i 's/--address.*:/--address 0.0.0.0:9000 /g' "
                    "/etc/systemd/system/minio.service || true"
                ),
                "sudo systemctl daemon-reload",
                "sudo systemctl start minio",
            ],
            "cause_4_localhost_only": [
                "sudo systemctl stop minio",
                (
                    "sudo sed -i 's/127.0.0.1:9000/0.0.0.0:9000/g' "
                    "/etc/systemd/system/minio.service || true"
                ),
                "sudo systemctl daemon-reload",
                "sudo systemctl start minio",
            ],
            "cause_5_firewall": [
                "sudo ufw allow 9000/tcp || true",
                "sudo ufw allow 9001/tcp || true",
                "sudo ufw reload || true",
                "sudo iptables -I INPUT -p tcp --dport 9000 -j ACCEPT || true",
            ],
        },
        "verification_commands": [
            "which minio",
            "sudo systemctl is-active minio",
            "ss -tuln | grep 9000",
            "sudo ufw status",
            "curl -sf http://localhost:9000/minio/health/live && echo HEALTHY || echo UNREACHABLE",
        ],
    }
}

# ══════════════════════════════════════════════════════════════
# COMMAND WHITELIST — executor will reject anything not matching
# ══════════════════════════════════════════════════════════════

ALLOWED_COMMAND_PREFIXES = [
    "which", "ps aux", "sudo systemctl", "ss -tuln", "sudo ufw",
    "sudo iptables", "curl", "wget", "chmod", "sudo mv", "sudo useradd",
    "sudo mkdir", "sudo chown", "sudo tee", "sudo sed", "sudo journalctl",
    "echo", "sleep", "cat", "ls", "sudo usermod", "systemctl", "netstat", "iptables", "ss", "sudo cat", 
]

# ══════════════════════════════════════════════════════════════
# LLM CALL
# ══════════════════════════════════════════════════════════════

def call_llm(messages: list[dict]) -> str:
    """Send messages to OpenRouter and return response text."""
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.1,
        },
        timeout=60,
    )
    
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()

def strip_json_fence(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()

# ══════════════════════════════════════════════════════════════
# PROMPT 1 — initial analysis, runs once
# ══════════════════════════════════════════════════════════════

def build_prompt_1(task_id: str, error_message: str, registry_entry: dict) -> list[dict]:
    """
    Builds the initial prompt. Gives the LLM minimal context.
    """
    system = (
        "You are an automated infrastructure repair agent for HPE PCAI systems. "
        "You diagnose and fix failures on Linux worker nodes via SSH commands. "
        "Always respond with valid JSON only, no prose."
    )

    user = f"""TASK: {task_id}
ERROR: {error_message}
CONTEXT: This error is related to minio

DO NOT use backslashes (\\) in your output. Use forward slashes (/) for paths instead.
Return a JSON object in this exact format:
{{
    "reasoning": "one sentence based ONLY on the error message",
    "next_commands": ["command 1", "command 2"],
    "phase": "diagnostic"
}}"""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


def build_prompt_2(
    error_message: str,
    registry_entry: dict,
    command_history: list[dict],
) -> list[dict]:
    """
    Builds the iteration prompt. No registry causes or fix commands provided.
    """
    system = (
        "You are an automated infrastructure repair agent. "
        "Always respond with valid JSON only, no prose."
    )

    user = f"""ERROR: {error_message}
CONTEXT: This error is related to MinIO.

COMMANDS RUN SO FAR:
{command_history}

Decide what to do next. Be decisive, if you think the problem is solved and the original command can be run again safely, then be confident.

Return JSON:
{{
    "reasoning": "one sentence based on current outputs",
    "next_commands": ["command 1", "command 2"],
    "phase": "diagnostic"
}}

Or if done:
{{
    "reasoning": "one sentence confirming resolution",
    "next_commands": [],
    "phase": "done"
}}"""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

# ══════════════════════════════════════════════════════════════
# MAIN GENERATOR LOGIC
# ══════════════════════════════════════════════════════════════

class FixGeneratorAgent:

    def __init__(self, task_id: str, error_message: str):
        self.task_id       = task_id
        self.error_message = error_message

        registry_entry = FIX_REGISTRY.get(task_id)
        if not registry_entry:
            raise ValueError(f"No FIX_REGISTRY entry for task_id: {task_id}")

        self.registry_entry = registry_entry

    def get_first_batch(self) -> dict:
        """
        Runs Prompt 1 once. Returns the first batch of commands
        to send to the fix executor.
        """
        print(f"[FixGenerator] Running Prompt 1 for task: {self.task_id}")
        messages  = build_prompt_1(self.task_id, self.error_message, self.registry_entry)
        raw       = call_llm(messages)
        parsed    = json.loads(strip_json_fence(raw))

        print(f"[FixGenerator] Prompt 1 reasoning: {parsed.get('reasoning')}")
        print(f"[FixGenerator] Phase: {parsed.get('phase')}")
        print(f"[FixGenerator] Commands: {parsed.get('next_commands')}")
        return parsed

    def get_next_batch(self, command_history: list[dict]) -> dict:
        """
        Runs Prompt 2 with accumulated command history.
        Returns next commands or phase=done.
        """
        print(f"\n[FixGenerator] Running Prompt 2 "
              f"(history: {len(command_history)} commands so far)")
        messages = build_prompt_2(
            self.error_message,
            self.registry_entry,
            command_history,
        )
        raw    = call_llm(messages)
        parsed = json.loads(strip_json_fence(raw))

        print(f"[FixGenerator] Prompt 2 reasoning: {parsed.get('reasoning')}")
        print(f"[FixGenerator] Phase: {parsed.get('phase')}")
        print(f"[FixGenerator] Commands: {parsed.get('next_commands')}")
        return parsed