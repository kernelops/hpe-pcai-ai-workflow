"""
knowledge_base.py
Builds and manages the ChromaDB knowledge base.
Contains:
- HPE documentation snippets
- Real MinIO installation + configuration errors with fixes
- NFS configuration errors with fixes
- OS validation errors with fixes
All error text and diagnosis/solution combined into 'text' field for proper RAG retrieval.
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict

# Collection names
DOCS_COLLECTION = "hpe_docs"
ERRORS_COLLECTION = "past_errors"

# --- HPE Documentation ---
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

# --- Past Errors & Fixes ---
MOCK_PAST_ERRORS = [

    # --- Mock iLO Error ---
    {
        "id": "err_001",
        "text": "Error: ConnectionRefusedError during iLO configuration task. "
                "Task: configure_ilo | iLO IP 192.168.1.10 port 443 refused connection. "
                "Diagnosis: iLO network interface not enabled after factory reset. "
                "Solution: Enable iLO dedicated network port via physical server access. Re-run configure_ilo task. "
                "Prevention: Always verify iLO network interface is enabled before running configure_ilo task.",
        "source": "Past Error Log #001 - iLO Configuration"
    },

    # --- MinIO Installation Errors ---
    {
        "id": "err_002",
        "text": "Error: wget: unable to resolve host address. "
                "Diagnosis: DNS resolution failure. System cannot resolve hostname to IP address. "
                "Causes: no internet connectivity, DNS server not configured or unreachable, incorrect /etc/resolv.conf, firewall blocking DNS queries. "
                "Solution: Check connectivity with ping google.com. Edit /etc/resolv.conf and add nameserver 8.8.8.8 as first line. "
                "Restart DNS: sudo systemctl restart systemd-resolved. "
                "Prevention: Configure stable DNS servers. Ensure firewall does not block DNS traffic.",
        "source": "MinIO Installation Error #002 - DNS Resolution"
    },
    {
        "id": "err_003",
        "text": "Error: Resolving domain_name failed: Temporary failure in name resolution. "
                "Diagnosis: System cannot resolve domain name to IP address. "
                "Causes: no internet connectivity, DNS not configured, incorrect /etc/resolv.conf, firewall blocking DNS. "
                "Solution: Test with ping google.com. Edit /etc/resolv.conf to add nameserver 8.8.8.8. "
                "Restart DNS: sudo systemctl restart systemd-resolved. Check nameservers with resolvectl status. "
                "Prevention: Configure reliable DNS servers. Verify firewall does not block DNS traffic.",
        "source": "MinIO Installation Error #003 - Name Resolution"
    },
    {
        "id": "err_004",
        "text": "Error: sudo: A terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper. "
                "Diagnosis: Script attempts to use sudo without interactive terminal TTY to prompt for password. "
                "Solution: Use -S flag to pipe password via stdin: echo $password | sudo -S /path/to/command. "
                "Or configure sudoers file to allow specific commands without password: myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio. "
                "Prevention: Always use passwordless sudo for specific commands in automated scripts by editing the sudoers file.",
        "source": "MinIO Installation Error #004 - Sudo TTY"
    },
    {
        "id": "err_005",
        "text": "Error: sudo: A password is required. "
                "Diagnosis: Automated script attempts to use sudo without interactive terminal. No TTY allocated. "
                "Solution: Use -S flag: echo $password | sudo -S /path/to/command. "
                "Or configure sudoers: myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio. "
                "Prevention: Always configure passwordless sudo for specific commands in scripts via sudoers file.",
        "source": "MinIO Installation Error #005 - Sudo Password"
    },
    {
        "id": "err_006",
        "text": "Error: command not found. "
                "Diagnosis: Command or executable does not exist in PATH variable locations. "
                "Solution: Execute with absolute path: ~/script or ./script. "
                "Add directory to PATH: export PATH=$PATH:/path/to/directory. "
                "Install missing package containing the command. Verify with: which command_name. "
                "Prevention: Place executables in PATH directories like ~/.local/bin. Add directories to PATH in .bashrc.",
        "source": "MinIO Installation Error #006 - Command Not Found"
    },
    {
        "id": "err_007",
        "text": "Error: SSH operator exit status 127. Command not found on remote host. "
                "Diagnosis: Remote system cannot find executable in PATH variable. "
                "Solution: Verify command exists with: which command_name. "
                "Check PATH: echo $PATH. Add to PATH: export PATH=$PATH:/path/to/directory. "
                "Install missing package. Use full absolute path to command. "
                "Prevention: Verify command installation and PATH before execution.",
        "source": "MinIO Installation Error #007 - SSH Exit 127"
    },
    {
        "id": "err_008",
        "text": "Error: No such file or directory at specified file_path. "
                "Diagnosis: System cannot find file or directory at provided path. File deleted, moved, or path has typo. "
                "Solution: Use absolute paths in scripts. Ensure correct working directory. "
                "Check path spelling carefully. Verify previous commands executed successfully if file should be generated. "
                "Prevention: Always use absolute paths. Implement file existence checks before access.",
        "source": "MinIO Installation Error #008 - File Not Found"
    },
    {
        "id": "err_009",
        "text": "Error: Failed to enable unit: Unit file service_name.service does not exist. "
                "Diagnosis: systemd service file missing from expected location /etc/systemd/system/ or /lib/systemd/system/. "
                "Causes: service never installed, wrong filename, installation failed earlier. "
                "Solution: Check if service file exists: ls /etc/systemd/system/service_name.service. "
                "If missing install or create the service. Reload: sudo systemctl daemon-reload. "
                "Enable: sudo systemctl enable --now service_name. "
                "Prevention: Add validation step to check service file exists before running systemctl enable.",
        "source": "MinIO Installation Error #009 - Service File Missing"
    },

    # --- MinIO Configuration Errors ---
    {
        "id": "err_010",
        "text": "Error: mc: Deprecated command. Please use mc admin policy attach. "
                "Diagnosis: mc admin policy set command deprecated and replaced with mc admin policy attach in newer MinIO client versions. "
                "Solution: Replace deprecated command with new syntax: mc admin policy attach local readwrite --user=MINIO_USER. "
                "Use mc admin policy attach instead of mc admin policy set. "
                "Prevention: Check MinIO client version and review changelogs when upgrading. Use mc --help to verify current syntax.",
        "source": "MinIO Configuration Error #010 - Deprecated mc Command"
    },
    {
        "id": "err_011",
        "text": "Error: mc: Unable to initialize new alias from provided credentials. Connection refused at IP_ADDRESS:PORT_NUMBER. dial tcp connect: connection refused. "
                "Diagnosis: MinIO client cannot connect to MinIO server. No service listening on that port. MinIO not running or running on different port. "
                "Solution: Check if MinIO running: ps aux | grep minio. "
                "Start MinIO if not running: minio server /data --console-address :9001. "
                "Verify correct port: netstat -tuln | grep 9000. Port 9000 is default API port. "
                "Update mc alias with correct endpoint. "
                "Prevention: Verify MinIO is running on correct port before configuring aliases.",
        "source": "MinIO Configuration Error #011 - Connection Refused"
    },
    {
        "id": "err_012",
        "text": "Error: Command exited with return code 1. Generic failure. "
                "Diagnosis: Generic failure message. Exact cause found in earlier log output. "
                "Solution: Check earlier logs for ERROR or Exception messages. Find root cause and fix underlying issue. "
                "Prevention: Log detailed command output including stdout and stderr. Add explicit error messages in scripts.",
        "source": "MinIO Configuration Error #012 - Exit Code 1"
    },
    {
        "id": "err_013",
        "text": "Error: Unable to find image minio/minio:IMAGE_TAG locally. Docker image not found. "
                "Diagnosis: Docker cannot find specified image locally and cannot pull from registry. Tag invalid or mistyped. "
                "Solution: Verify available images: docker images | grep minio. "
                "Pull valid tag: docker pull minio/minio:latest. "
                "Load from tar file if exported: docker load -i minio_image.tar. "
                "Prevention: Pre-pull or pre-load images before deployment. Validate image existence before running containers.",
        "source": "MinIO Configuration Error #013 - Docker Image Not Found"
    },
    {
        "id": "err_014",
        "text": "Error: docker: Error response from daemon: manifest for minio/minio:IMAGE_TAG not found: manifest unknown. "
                "Diagnosis: Docker connected to registry but tag does not exist. Tag misspelled, never published, or repo name incorrect. "
                "Solution: List available tags: skopeo list-tags docker://minio/minio. "
                "Pull valid tag: docker pull minio/minio:latest. Update command with correct tag. "
                "Prevention: Verify image tags exist before deployment. Implement tag validation step.",
        "source": "MinIO Configuration Error #014 - Docker Manifest Not Found"
    },
    {
        "id": "err_015",
        "text": "Error: SSH operator error exit status 125. Docker daemon error on remote host. "
                "Diagnosis: SSH command on remote host failed with exit code 125. Indicates Docker daemon error, invalid image reference, pull failure, or container creation issue. "
                "Solution: Check full command output above error to identify specific failure. Correct accordingly. "
                "Prevention: Use Docker operations with proper error handling. Log full command output.",
        "source": "MinIO Configuration Error #015 - SSH Exit 125 Docker Error"
    },
    {
        "id": "err_016",
        "text": "Error: mc: invalid retention mode INVALIDMODE. Invalid arguments provided. "
                "Diagnosis: mc command failed because invalid retention mode specified. Valid modes are governance or compliance only. "
                "Solution: Verify retention modes: mc retention set --help. "
                "Check current settings: mc retention info BUCKET_NAME. "
                "Correct mode to valid value: governance or compliance. "
                "Prevention: Validate retention mode arguments against allowed values before executing mc commands.",
        "source": "MinIO Configuration Error #016 - Invalid Retention Mode"
    },
    {
        "id": "err_017",
        "text": "Error: curl: (22) The requested URL returned error: 403 Forbidden. "
                "Diagnosis: curl accessed endpoint that returned HTTP 403. Request understood but access denied due to insufficient permissions. Credentials not provided or user lacks permission. "
                "Solution: Include authentication credentials in curl request. Check available endpoints. Use valid endpoint path. "
                "Prevention: Verify endpoint paths before scripting. Test with valid credentials. Always include auth credentials for protected endpoints.",
        "source": "MinIO Configuration Error #017 - HTTP 403 Forbidden"
    },
    {
        "id": "err_018",
        "text": "Error: SSH operator error exit status 22. curl HTTP 404 error on remote host. "
                "Diagnosis: curl exit code 22 indicates requested URL not found, HTTP 404 error. curl connected but server returned error. "
                "Solution: Check command output above error for specific failure. Verify command syntax and arguments. "
                "Ensure URLs correctly formatted and authentication credentials included. "
                "Prevention: Validate command arguments before execution. Use proper error handling and logging.",
        "source": "MinIO Configuration Error #018 - SSH Exit 22 HTTP 404"
    },
    {
        "id": "err_019",
        "text": "Error: mc: Unable to initialize new alias from provided credentials. The request signature we calculated does not match the signature you provided. Check your key and signing method. "
                "Diagnosis: mc failed to authenticate with MinIO server. Credentials incorrect, system time out of sync, or server not ready. "
                "Causes: wrong access key or secret key, client and server time out of sync, MinIO not fully initialized, HTTP vs HTTPS mismatch, special characters in keys. "
                "Solution: Check MinIO credentials: docker exec minio_server env | grep MINIO_ROOT. "
                "Add health check before alias: curl -s http://127.0.0.1:PORT/minio/health/live. "
                "Sync system time: sudo timedatectl set-ntp true. "
                "Set alias with correct credentials: mc alias set local http://127.0.0.1:9000 MINIO_ROOT_USER MINIO_ROOT_PASSWORD. "
                "Prevention: Implement server health check before mc commands. Keep system time synchronized with NTP.",
        "source": "MinIO Configuration Error #019 - Signature Mismatch"
    },
    {
        "id": "err_020",
        "text": "Error: mc: Unable to create new policy: invalid character ] after object key:value pair. JSON parse error. "
                "Diagnosis: JSON file has syntax error. Found ] where key:value content or closing } expected. "
                "Causes: missing } to close object, extra or misplaced ], incomplete key-value pair, improper nesting. "
                "Solution: Use jq to find exact error location: jq . /path/to/policy.json. "
                "Fix JSON structure: nano /path/to/policy.json. Validate: jq . /path/to/policy.json. Rerun command. "
                "Prevention: Always validate JSON files before using them.",
        "source": "MinIO Configuration Error #020 - JSON Syntax Error"
    },
    {
        "id": "err_021",
        "text": "Error: syntax error: unexpected end of file in bash script. "
                "Diagnosis: Interpreter reached end of file while expecting open construct to be closed. "
                "Causes: missing fi for if block, missing done for loop, unclosed quotes, unclosed braces, incomplete multi-line command. "
                "Solution: Inspect file: cat /path/to/file. Fix structure in editor: nano /path/to/file. Revalidate and rerun. "
                "Prevention: Always run syntax check before execution: bash -n script.sh.",
        "source": "MinIO Configuration Error #021 - Bash Syntax Error"
    },
    {
        "id": "err_022",
        "text": "Error: req: Unknown option or message digest. openssl command error. "
                "Diagnosis: openssl req command received invalid argument. Does not recognize option/flag or message digest algorithm. "
                "Causes: typo in flag, unsupported digest algorithm, wrong argument order, incompatible openssl version. "
                "Solution: Verify valid options: openssl req -help. "
                "Check supported digests: openssl list -digest-algorithms. Fix command. Check version: openssl version. "
                "Prevention: Always check help before using commands. Avoid typos in flags. Use widely supported digests.",
        "source": "MinIO Configuration Error #022 - OpenSSL Invalid Option"
    },

    # --- NFS Configuration Errors ---
    {
        "id": "err_023",
        "text": "Error: Error response from daemon: No such container: CONTAINER_NAME. "
                "Diagnosis: Docker daemon cannot find container with given name or ID. Container does not exist, was removed, stopped, or referenced incorrectly. "
                "Causes: typo in container name or ID, container was deleted, container not yet created, trying to access stopped container incorrectly. "
                "Solution: List running containers: docker ps. List all containers including stopped: docker ps -a. "
                "Start container if stopped: docker start CONTAINER_NAME. Re-run container if removed: docker run IMAGE_NAME. "
                "Verify container name: docker ps -a --format '{{.Names}}'. "
                "Prevention: Check container status before operations with docker ps -a. Be careful with --rm flag.",
        "source": "NFS Configuration Error #023 - Docker No Such Container"
    },
    {
        "id": "err_024",
        "text": "Error: SSH command timed out. "
                "Diagnosis: SSH connection attempted but no response received within allowed time. "
                "Causes: target machine is down or unreachable, network issues such as wrong IP or DNS failure or firewall blocking, SSH service not running on remote machine, or long-running command exceeding timeout limit. "
                "Solution: Check if target machine is reachable: ping TARGET_MACHINE. "
                "Check if SSH port 22 is open: nc -zv TARGET_MACHINE 22. "
                "Try manual SSH with verbose output: ssh -vvv user@TARGET_MACHINE. "
                "Confirm SSH server is active: sudo systemctl status ssh. Start if needed: sudo systemctl start ssh. "
                "Increase timeout for long commands: ssh -o ConnectTimeout=30 user@TARGET_MACHINE. "
                "Verify firewall allows port 22: sudo ufw status. If blocked: sudo ufw allow 22. "
                "Prevention: Ensure SSH service is always running with sudo systemctl enable ssh. Set appropriate timeouts in scripts.",
        "source": "NFS Configuration Error #024 - SSH Timeout"
    },
    {
        "id": "err_025",
        "text": "Error: ERROR: nfs module is not loaded in the Docker host's kernel (try: modprobe nfs). "
                "Diagnosis: Host system is trying to use NFS functionality but required kernel module is not loaded. Docker or another service cannot access NFS-based storage without it. "
                "Causes: NFS kernel module not loaded, NFS support not installed, insufficient privileges to load kernel modules, running inside minimal or stripped-down OS. "
                "Solution: Load the NFS kernel module dynamically: sudo modprobe nfs. "
                "Verify module is loaded: lsmod | grep nfs. "
                "Install NFS utilities if missing: sudo apt update && sudo apt install nfs-common. "
                "Retry command on target machine. "
                "Prevention: Ensure NFS module loads automatically on startup: echo 'nfs' | sudo tee -a /etc/modules. "
                "Verify NFS dependencies before deployment. Avoid minimal OS images without NFS support.",
        "source": "NFS Configuration Error #025 - NFS Kernel Module Not Loaded"
    },
    {
        "id": "err_026",
        "text": "Error: exportfs: /etc/exports: unknown keyword UNKNOWN_KEYWORD. "
                "Diagnosis: exportfs command failed because /etc/exports contains an invalid NFS export option not recognized by the parser. NFS exports cannot be applied. "
                "Causes: typo in export option, unsupported or invalid keyword, wrong syntax or format in /etc/exports, mixing options from different NFS versions. "
                "Solution: Inspect current NFS exports configuration: cat /etc/exports. "
                "Look for unknown or misspelled options and edit: sudo nano /etc/exports. "
                "Validate exports configuration: sudo exportfs -ra. "
                "Restart NFS service if needed: sudo systemctl restart nfs-kernel-server. "
                "Prevention: Follow correct NFS syntax strictly. Validate after every change with sudo exportfs -ra. Backup /etc/exports before making changes.",
        "source": "NFS Configuration Error #026 - Invalid NFS Export Option"
    },

    # --- OS Validation Errors ---
    {
        "id": "err_027",
        "text": "Error: ping: INVALID_HOSTNAME: Name or service not known. "
                "Diagnosis: System cannot resolve provided hostname. Failed to convert name to IP address using DNS or local resolution. "
                "Causes: typo in hostname, DNS server not configured or unreachable, no network connectivity, missing or incorrect /etc/hosts entry, service name does not exist. "
                "Solution: Test with a known valid domain: ping google.com. If it works, original hostname is wrong. If it fails, no internet connectivity. "
                "Query DNS directly: nslookup HOSTNAME. "
                "Check DNS configuration: cat /etc/resolv.conf. "
                "Add temporary host entry if needed: sudo nano /etc/hosts. "
                "Restart networking if DNS issue: sudo systemctl restart NetworkManager. "
                "Prevention: Verify hostnames before use. Keep valid nameservers in /etc/resolv.conf. Use IP addresses for critical operations.",
        "source": "OS Validation Error #027 - Name or Service Not Known"
    },
    {
        "id": "err_028",
        "text": "Error: Command exited with return code 2. "
                "Diagnosis: Command finished execution but returned exit code 2 indicating incorrect usage, syntax error, invalid arguments, misconfiguration, or missing file or option. "
                "Causes: wrong flags or parameters passed, missing required arguments, tool-specific validation failure, invalid file paths or inputs. "
                "Solution: Rerun command to see real error message above this return code. Print last exit code: echo $?. "
                "Check command usage: COMMAND --help. "
                "Ensure required files exist: ls -l /path/to/file. "
                "Prevention: Always validate command syntax before running. Test commands incrementally.",
        "source": "OS Validation Error #028 - Exit Code 2"
    },
    {
        "id": "err_029",
        "text": "Error: df: unrecognized option OPTION. "
                "Diagnosis: df command received a flag or option it does not support. Command-line parser does not recognize the argument. "
                "Causes: typo in the option, using an option from a different OS, running in minimal environment where df supports fewer flags. "
                "Solution: Check valid flags for current df version: df --help. "
                "Try common valid options: df -h. "
                "Check df version: df --version. "
                "Install full utilities if needed: sudo apt update && sudo apt install coreutils. "
                "Prevention: Always check command compatibility. Use portable options like -h and -k. Avoid copying commands from incompatible systems.",
        "source": "OS Validation Error #029 - df Unrecognized Option"
    },
    {
        "id": "err_030",
        "text": "Error: free: unrecognized option OPTION. "
                "Diagnosis: free command received a flag it does not support. Command exists but environment version does not recognize the option. "
                "Causes: typos in the option, using flags from another Linux version, running inside minimal environment, incorrect flag syntax, older version of free with limited features. "
                "Solution: Check which version of free is being used: free --version. "
                "Display all valid flags: free --help. "
                "Try common valid options: free -h. "
                "Install full utilities if needed: sudo apt update && sudo apt install procps. "
                "Prevention: Check command options before use. Avoid copying commands blindly across different OSes. Use widely supported options like -m.",
        "source": "OS Validation Error #030 - free Unrecognized Option"
    },
    {
        "id": "err_031",
        "text": "Error: curl: Failed to connect to localhost port PORT: Connection refused. "
                "Diagnosis: curl command failed because it could not establish TCP connection to specified host and port. Connection actively refused meaning no service is listening on that port or firewall is rejecting it. "
                "Causes: target service is not running, service is running on different port, service crashed, port not exposed, or firewall blocking the port. "
                "Solution: Check if any service is listening on the port: ss -tuln | grep PORT. "
                "Check if required service is running: ps aux | grep SERVICE_NAME. "
                "Start the service if not running. "
                "Verify service is configured to run on expected port: cat config.yaml. "
                "If using Docker, confirm container is running and check port mapping. "
                "Prevention: Always verify service is running before connecting. Use health checks to confirm service availability.",
        "source": "OS Validation Error #031 - curl Connection Refused"
    },
    {
        "id": "err_032",
        "text": "Error: Command exited with return code 7. "
                "Diagnosis: Command executed but failed with exit code 7. For curl, exit code 7 specifically indicates failure to connect to the host such as connection refused, host unreachable, or timeout. "
                "Causes: target service not running, wrong host or port, port is closed or not listening, network or firewall restrictions. "
                "Solution: Identify which command failed: history | tail -n 5. "
                "If using curl, retry with verbose output: curl -v http://HOST:PORT. "
                "Check if service is running: ss -tuln | grep PORT. "
                "Check connectivity: ping HOST. "
                "If using Docker, ensure container is running and check port mapping. "
                "Prevention: Verify service before connecting. Use correct host and port. Confirm server readiness before requests.",
        "source": "OS Validation Error #032 - Exit Code 7"
    },
    {
        "id": "err_033",
        "text": "Error: touch: cannot touch FILE: Permission denied. "
                "Diagnosis: touch command tried to create or modify a file but OS denied permission. "
                "Causes: user does not have write permission in directory, file or directory owned by another user such as root, attempting to write in restricted location like /root or /etc or /sys, file is read-only, or running inside container with limited privileges. Note: /sys is a read-only virtual filesystem. Even with sudo, arbitrary file creation in /sys is not allowed as it represents kernel objects. "
                "Solution: Check directory permissions: ls -ld DIRECTORY. "
                "Check file ownership: ls -l FILE. "
                "Run as root if allowed: sudo touch FILE. "
                "Change permissions if you own the file: chmod u+w FILE. "
                "Change ownership if needed: sudo chown $USER:$USER FILE_OR_DIRECTORY. "
                "Use a writable directory: touch ~/FILE. "
                "Prevention: Work in user-owned directories. Check permissions before writing. Set correct permissions during setup.",
        "source": "OS Validation Error #033 - Permission Denied touch"
    },
    {
        "id": "err_034",
        "text": "Error: Command exited with return code 3. "
                "Diagnosis: Command executed but returned exit code 3 indicating failure. For systemctl is-active SERVICE, return code 3 means the service is inactive or does not exist. "
                "Causes: service or process is not running, invalid state for the requested operation, configuration or runtime condition not satisfied. "
                "Solution: Identify the command that failed: history | tail -n 5. "
                "Verify the correct service name: systemctl list-units --type=service --all. "
                "Check if service exists in systemd: systemctl list-unit-files. "
                "Use correct service name. Install the service if needed: sudo apt update && sudo apt install SERVICE. "
                "Check service status for detailed information: systemctl status SERVICE_NAME. "
                "Prevention: Validate service existence before checking status. Use idempotent checks that handle missing services gracefully.",
        "source": "OS Validation Error #034 - Exit Code 3"
    },
]


def get_embedding_function():
    """Returns sentence-transformers embedding function for ChromaDB."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-mpnet-base-v2",
        cache_folder="./model_cache"
    )


def build_knowledge_base(persist_dir: str = "./chroma_db") -> chromadb.ClientAPI:
    """
    Initializes ChromaDB, creates collections, and ingests data.
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
