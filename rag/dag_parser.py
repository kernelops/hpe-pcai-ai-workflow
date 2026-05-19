"""
dag_parser.py
Parses DAG source code to extract all commands present in it.
"""

import re
from typing import List

# Non-MC commands (multi-word supported)
_NON_MC_COMMANDS = [
    "mkdir",
    "chmod",
    "docker rm",
    "docker run",
    "modprobe",
    "docker ps",
    "docker logs",
    "docker volume rm",
    "docker volume create",
    "docker exec",
    "uname",
    "id",
    "test",
    "exportfs",
    "systemctl enable",
    "curl",
    "apt-get update",
    "apt-get install",
    "wget",
    "virsh destroy",
    "virsh undefine",
    "virt-install",
    "virsh domstate",
    "virsh dominfo",
    "lsb_release",
    "systemctl stop",
    "killall",
    "dpkg",
    "openssl req",
]

# Pattern to KB command mapping for mc commands
_MC_PATTERN_TO_COMMAND = {
    r"mc\s+--?\w*\s+alias\s+set": "mc alias set",
    r"mc\s+--?\w*\s+admin\s+user\s+add": "mc admin user add",
    r"mc\s+--?\w*\s+admin\s+policy\s+create": "mc admin policy create",
    r"mc\s+--?\w*\s+admin\s+policy\s+attach": "mc admin policy attach",
    r"mc\s+--?\w*\s+mb\s+": "mc mb",
    r"mc\s+--?\w*\s+version\s+enable": "mc version enable",
    r"mc\s+--?\w*\s+ilm\s+rule\s+add": "mc ilm rule add",
    r"mc\s+--?\w*\s+retention\s+set": "mc retention set",
}


def extract_non_mc_commands(dag_source: str) -> List[str]:
    """
    Extract non-MC commands.
    Handles multi-word commands and line continuations (backslashes).
    """
    found = set()
    
    # Remove line continuations (backslash at end of line)
    cleaned = re.sub(r'\\\s*\n', ' ', dag_source)
    
    for cmd in _NON_MC_COMMANDS:
        # Build pattern: command as whole word(s), not part of larger word
        pattern = r'\b' + r'\s+'.join(re.escape(word) for word in cmd.split()) + r'\b'
        if re.search(pattern, cleaned):
            found.add(cmd)
    
    return list(found)


def extract_mc_commands(dag_source: str) -> List[str]:
    """
    Extract mc commands by scanning line-by-line.
    Handles flags and line continuations.
    """
    found = set()
    
    # Remove line continuations first
    cleaned = re.sub(r'\\\s*\n', ' ', dag_source)
    lines = cleaned.splitlines()
    
    for line in lines:
        if "mc" not in line:
            continue
        
        # Skip lines where mc is just an image name (minio/mc without command string)
        if "minio/mc" in line and "-c" not in line and "&&" not in line and ";" not in line:
            continue
        
        for pattern, command in _MC_PATTERN_TO_COMMAND.items():
            if re.search(pattern, line):
                found.add("mc")
                found.add(command)
                break
    
    return list(found)


def extract_commands_from_dag(dag_source: str) -> List[str]:
    """
    Extract all commands from DAG source code.
    Returns deduplicated list of commands suitable for RAG lookup.
    """
    non_mc = extract_non_mc_commands(dag_source)
    mc = extract_mc_commands(dag_source)
    
    return list(set(non_mc + mc))