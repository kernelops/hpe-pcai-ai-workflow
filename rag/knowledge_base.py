"""
knowledge_base.py
Builds and manages the ChromaDB knowledge base.
Contains:
- Mock HPE documentation snippets
- Mock past error logs + their fixes
Swap mock data with real PDFs/docs later.
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict

# Collection names
DOCS_COLLECTION = "hpe_docs"
ERRORS_COLLECTION = "past_errors"

# --- Mock HPE Documentation ---
MOCK_HPE_DOCS = [
    {
        "id": "doc_001",
        "text": "HPE iLO Configuration: iLO (Integrated Lights-Out) requires network configuration before OS deployment. "
                "Ensure iLO IP is reachable and credentials are set. Common errors include 'Connection refused' when "
                "iLO port 443 is blocked, and 'Authentication failed' when default credentials haven't been changed. "
                "Fix: Verify network connectivity with ping, check firewall rules for port 443, reset iLO credentials via physical access.",
        "source": "HPE iLO Setup Guide"
    },
    {
        "id": "doc_002",
        "text": "SPP (Service Pack for ProLiant) Deployment: SPP must match the server hardware generation. "
                "Deploying wrong SPP version causes 'Incompatible firmware' errors. "
                "Always verify server model against SPP release notes before deployment. "
                "Fix: Download correct SPP ISO from HPE portal, verify checksum, remount and retry.",
        "source": "HPE SPP Deployment Guide"
    },
    {
        "id": "doc_003",
        "text": "OS Deployment on HPE Servers: OS installation via automated pipeline requires correct boot order. "
                "Errors like 'No bootable device found' occur when PXE boot is not enabled or BIOS boot mode mismatch (UEFI vs Legacy). "
                "Fix: Enter BIOS, enable PXE boot, ensure boot mode matches OS installer (UEFI for modern OS).",
        "source": "HPE OS Deployment Guide"
    },
    {
        "id": "doc_004",
        "text": "MinIO Object Storage Configuration: MinIO requires correct endpoint URL, access key and secret key. "
                "Errors include 'S3 endpoint unreachable', 'Access Denied', and 'Bucket not found'. "
                "Fix: Verify MinIO service is running (systemctl status minio), check access/secret keys in config, "
                "create bucket manually if missing using mc mb command.",
        "source": "MinIO on HPE PCAI Guide"
    },
    {
        "id": "doc_005",
        "text": "Network Configuration on PCAI Rack: Aruba and NVIDIA switches require VLAN configuration for inter-node communication. "
                "Errors include 'Host unreachable' between control and worker nodes, caused by missing VLAN tags. "
                "Fix: SSH into switch, verify VLAN config, add missing VLAN tags to relevant ports.",
        "source": "HPE PCAI Network Guide"
    },
    {
        "id": "doc_006",
        "text": "NFS Configuration: NFS server must be running on control node before worker nodes attempt to mount. "
                "Error 'mount.nfs: Connection timed out' means NFS service is down or firewall is blocking port 2049. "
                "Fix: Run 'systemctl start nfs-server' on control node, open port 2049 in firewall.",
        "source": "HPE PCAI Storage Guide"
    },
    {
        "id": "doc_007",
        "text": "GLFS (GlusterFS) Cluster Setup: GlusterFS peer probe fails when hostname resolution fails between nodes. "
                "Error: 'Probe returned with unknown errno 107'. "
                "Fix: Ensure /etc/hosts has entries for all nodes, verify glusterd service is running on all nodes.",
        "source": "HPE PCAI GLFS Guide"
    },
]


MOCK_PAST_ERRORS = [
    # ---Mock Error ---
    {
        "id": "err_001",
        "text": "Error: ConnectionRefusedError during iLO configuration task. "
                "Task: configure_ilo | iLO IP 192.168.1.10 port 443 refused connection. "
                "Root Cause: iLO network interface not enabled after factory reset. "
                "Fix Applied: Enabled iLO dedicated network port via physical server access, re-ran configure_ilo task successfully.",
        "source": "Past Error Log #001"
    },
    #---Actual error logs for installation of MinIO---
    {
        "id": "err_002",
        "text":"wget: unable to resolve host address",
               
        "source":"Diagnosis: The system cannot resolve the hostname to an IP address. This indicates a DNS resolution failure. Possible underlying issues are no internet connectivity, DNS server not configured or not reachable, incorrect or empty /etc/resolv.conf, firewall/proxy blocking DNS queries or temporary DNS server failure."
                "Solution: Check network connectivity and DNS resolution with ping (e.g. ping google.com). Edit /etc/resolv.conf and add reliable DNS servers (Put nameserver 8.8.8.8 to the first line of /etc/resolv.conf). Restart DNS services (e.g. sudo systemctl restart systemd-resolved)."
                "Prevention: Ensure stable network connection. Configure stable DNS servers. Monitor DNS resolution regularly. Verify firewall settings do not block DNS traffic. "
                "Error_type: Network configuration"
                "Severity: Medium"
                "Retrieved_sources: https://stackoverflow.com/questions/24821521/wget-unable-to-resolve-host-address-http"
    },
    {
        "id": "err_003",
        "text": "Resolving <domain_name> failed: Temporary failure in name resolution",
                
        "source": "Diagnosis: System cannot resolve the domain name to an IP address. Possible causes include no internet connectivity, DNS server not configured or unreachable, incorrect/empty /etc/resolv.conf, firewall/proxy blocking DNS queries, or temporary DNS server failure."
                "Solution: Test connectivity with ping (e.g. ping google.com). Edit /etc/resolv.conf to add reliable DNS servers (e.g. nameserver 8.8.8.8). Restart DNS services (e.g. sudo systemctl restart systemd-resolved). Check if nameservers are configured in systemd-resolved with resolvectl status."
                "Prevention: Ensure stable network connection. Configure reliable DNS servers. Veify firewall settings do not block DNS traffic" 
                "Error_type: Network configuration"
                "Severity: Medium"
                "Retrieved_sources: https://unix.stackexchange.com/questions/504963/how-to-solve-a-temporary-failure-in-name-resolution-error "
    },
    {
        "id": "err_004",
        "text": "sudo: A terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper",
                
        "source": "Diagnosis: Occurs when a script or automated process attempts to use sudo without an interactive terminal (TTY) to prompt for a password. No TTY allocated."
                "Solution: Use the -S flag to pipe the password via stdin (echo $password | sudo -S /path/to/command) or (sudo -S /path/to/command < password.secret). This method is not recommended because a password can appear in logs and environment variables can be exposed. An alternate method is to configure /etc/sudoers file to allow specific commands without a password (E.g. myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio)."
                "Prevention: Always use passwordless sudo for specific commands in scripts by editing the sudoers file."
                "Error_type: Privilege escalation failure"
                "Severity: Medium - prevents command execution only when sudo requires authentication and no terminal is available."
                "Retrieved_sources: https://askubuntu.com/questions/1244898/sudo-a-terminal-is-required-to-read-the-password-either-use-the-s-option-to-r"
    },
    {
        "id": "err_005",
        "text": "sudo: A password is required",
                
        "source": "Diagnosis: Occurs when a script or automated process attempts to use sudo without an interactive terminal (TTY) to prompt for a password. No TTY allocated."
                "Solution: Use the -S flag to pipe the password via stdin (echo $password | sudo -S /path/to/command) or (sudo -S /path/to/command < password.secret). This method is not recommended because a password can appear in logs and environment variables can be exposed. An alternate method is to configure /etc/sudoers file to allow specific commands without a password (E.g. myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio)."
                "Prevention: Always use passwordless sudo for specific commands in scripts by editing the sudoers file."
                "Error_type: Privilege escalation failure"
                "Severity: Medium - prevents command execution only when sudo requires authentication and no terminal is available."
                "Retrieved_sources: https://askubuntu.com/questions/1244898/sudo-a-terminal-is-required-to-read-the-password-either-use-the-s-option-to-r"
    },
    {
        "id": "err_006",
        "text": "<command>: command not found",
                
        "source": "Diagnosis: Occurs when the script or file that the system is trying to execute doesn't exist in the location specified by the PATH variable."
                "Solution: Execute the file directly using its absolute or relative path (e.g., ~/script or ./script), or add a new directory containing the command to the PATH variable (export PATH=$PATH:/path/to/directory). Also, make sure to install the missing package containing the command. Make sure there are no typos in the command using which command (which <command>)."
                "Prevention: Always place custom executables in directories included in the PATH (e.g., ~/.local/bin), add new directories to PATH via shell configuration files like .bashrc for persistent changes across all future sessions, and ensure required packages are installed before attempting to run their commands."
                "Error_type: Configuration error"
                "Severity: Medium - task fails, but system is not corrupted, and the fix is typically simple"
                "Retrieved_sources: https://www.redhat.com/en/blog/fix-command-not-found-error-linux"
    },
    {
        "id": "err_007",
        "text": "Command exited with return code 127",
                
        "source": "Diagnosis: Indicates that the command was not found. This occurs when the system cannot locate the executable file in any of the paths defined by the PATH variable for the attempted command. "
                "Solution: Check that the command is typed correctly using the which command (which <command>). Check if the directory containing the command is included in the PATH variable (echo $PATH). If not, add it to PATH (export PATH=$PATH:/path/to/directory). Ensure that the required package providing the command is installed. Specify the full path to the command."
                "Prevention: Ensure the command or script exists and is executable by verifying its installation and path configuration before execution."
                "Error_type: Configuration error"
                "Severity: Medium - prevents command execution, but fix is typically straightforward and does not indicate deeper system issues."
                "Retrieved_sources: https://linuxconfig.org/how-to-fix-bash-127-error-return-code"
    },
    {
        "id": "err_008",
        "text": "No such file or directory: <file_path>",
                
        "source": "Diagnosis: The system cannot find the specified file or directory at the provided path. This can occur if the file was deleted, moved, or if there is a typo in the path. It can also happen if the script is being run from a different working directory than expected. Additionally, the file might require special permissions to access."
                "Solution:  Use absolute paths or ensure the script is run from the correct working directory. Check the exact path spelling. If the file is expected to be generated by a previous command, verify that command executed successfully."
                "Prevention: Always use absolute paths in scripts or ensure the working directory is correct. Implement error handling to check for file existence before attempting to access it."
                "Error_type: File System Error "
                "Severity: Medium - prevents file access, but fix is typically straightforward and does not indicate deeper system issues."
                "Retrieved_sources: "
    },
    # ---Actual error logs for configuration of MinIO---
    {
        "id": "err_009",
        "text": "mc: <Error> Deprecated command. Please use 'mc admin policy attach'",
                
        "source": "Diagnosis: The mc admin policy set command is deprecated and has been replaced with mc policy admin attach in newer versions of the MinIO client."
                "Solution: Replace the deprecated command with the new syntax: {MC_BINARY} admin policy attach local (readwrite|readonly|writeonly) --user={MINIO_USER}. Replaces mc admin policy (set|unset|update) commands with mc admin policy (attach|detach)."
                "Prevention: Always check the MinIO client version and review changelogs when upgrading, or use mc --help to verify current command syntax before scripting."
                "Error_type:  Configuration Error - using incorrect command syntax due to version mismatch or outdated script. "
                "Severity: Low - easily fixable by updating to the current command syntax."
                "Retrieved_sources: https://github.com/minio/mc/issues/4513, https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-policy/mc-admin-policy-attach/"
    },
]


def get_embedding_function():
    """Returns sentence-transformers embedding function for ChromaDB."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-mpnet-base-v2"
    )


def build_knowledge_base(persist_dir: str = "./chroma_db") -> chromadb.ClientAPI:
    """
    Initializes ChromaDB, creates collections, and ingests mock data.
    Safe to call multiple times — skips if already populated.
    """
    client = chromadb.PersistentClient(path=persist_dir)
    ef = get_embedding_function()

    # --- HPE Docs Collection ---
    docs_col = client.get_or_create_collection(
        name=DOCS_COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    if docs_col.count() == 0:
        print("[KnowledgeBase] Ingesting HPE documentation...")
        docs_col.add(
            ids=[d["id"] for d in MOCK_HPE_DOCS],
            documents=[d["text"] for d in MOCK_HPE_DOCS],
            metadatas=[{"source": d["source"]} for d in MOCK_HPE_DOCS],
        )
        print(f"[KnowledgeBase] Added {len(MOCK_HPE_DOCS)} HPE doc chunks.")
    else:
        print(f"[KnowledgeBase] HPE docs collection already has {docs_col.count()} entries.")

    # --- Past Errors Collection ---
    errors_col = client.get_or_create_collection(
        name=ERRORS_COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    if errors_col.count() == 0:
        print("[KnowledgeBase] Ingesting past error logs...")
        errors_col.add(
            ids=[e["id"] for e in MOCK_PAST_ERRORS],
            documents=[e["text"] for e in MOCK_PAST_ERRORS],
            metadatas=[{"source": e["source"]} for e in MOCK_PAST_ERRORS],
        )
        print(f"[KnowledgeBase] Added {len(MOCK_PAST_ERRORS)} past error entries.")
    else:
        print(f"[KnowledgeBase] Past errors collection already has {errors_col.count()} entries.")

    return client


def retrieve_context(
    query: str,
    client: chromadb.ClientAPI,
    top_k: int = 3
) -> List[Dict]:
    """
    Retrieves top_k relevant chunks from both collections for the given query.
    Returns combined list of results with source info.
    """
    ef = get_embedding_function()
    results = []

    for collection_name in [DOCS_COLLECTION, ERRORS_COLLECTION]:
        col = client.get_collection(name=collection_name, embedding_function=ef)
        query_results = col.query(
            query_texts=[query],
            n_results=min(top_k, col.count()),
        )
        for doc, meta in zip(query_results["documents"][0], query_results["metadatas"][0]):
            results.append({"text": doc, "source": meta.get("source", "Unknown")})

    return results
