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
    #---Actual error logs for installation of MinIO---
    {
        "id": "err_001",
        "text":"wget: unable to resolve host address",
               
        "source":"Diagnosis: The system cannot resolve the hostname to an IP address. This indicates a DNS resolution failure. Possible underlying issues are no internet connectivity, DNS server not configured or not reachable, incorrect or empty /etc/resolv.conf, firewall/proxy blocking DNS queries or temporary DNS server failure."
                "Solution: Check network connectivity and DNS resolution with ping (e.g. ping google.com). Edit /etc/resolv.conf and add reliable DNS servers (Put nameserver 8.8.8.8 to the first line of /etc/resolv.conf). Restart DNS services (e.g. sudo systemctl restart systemd-resolved)."
                "Prevention: Ensure stable network connection. Configure stable DNS servers. Monitor DNS resolution regularly. Verify firewall settings do not block DNS traffic. "
                "Error_type: Network configuration error"
                "Severity: Medium"
                "Retrieved_sources: https://stackoverflow.com/questions/24821521/wget-unable-to-resolve-host-address-http"
    },
    {
        "id": "err_002",
        "text": "Resolving <domain_name> failed: Temporary failure in name resolution",
                
        "source": "Diagnosis: System cannot resolve the domain name to an IP address. Possible causes include no internet connectivity, DNS server not configured or unreachable, incorrect/empty /etc/resolv.conf, firewall/proxy blocking DNS queries, or temporary DNS server failure."
                "Solution: Test connectivity with ping (e.g. ping google.com). Edit /etc/resolv.conf to add reliable DNS servers (e.g. nameserver 8.8.8.8). Restart DNS services (e.g. sudo systemctl restart systemd-resolved). Check if nameservers are configured in systemd-resolved with resolvectl status."
                "Prevention: Ensure stable network connection. Configure reliable DNS servers. Veify firewall settings do not block DNS traffic" 
                "Error_type: Network configuration error"
                "Severity: Medium"
                "Retrieved_sources: https://unix.stackexchange.com/questions/504963/how-to-solve-a-temporary-failure-in-name-resolution-error "
    },
    {
        "id": "err_003",
        "text": "sudo: A terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper",
                
        "source": "Diagnosis: Occurs when a script or automated process attempts to use sudo without an interactive terminal (TTY) to prompt for a password. No TTY allocated."
                "Solution: Use the -S flag to pipe the password via stdin (echo $password | sudo -S /path/to/command) or (sudo -S /path/to/command < password.secret). This method is not recommended because a password can appear in logs and environment variables can be exposed. An alternate method is to configure /etc/sudoers file to allow specific commands without a password (E.g. myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio)."
                "Prevention: Always use passwordless sudo for specific commands in scripts by editing the sudoers file."
                "Error_type: Privilege escalation failure"
                "Severity: Medium - prevents command execution only when sudo requires authentication and no terminal is available."
                "Retrieved_sources: https://askubuntu.com/questions/1244898/sudo-a-terminal-is-required-to-read-the-password-either-use-the-s-option-to-r"
    },
    {
        "id": "err_004",
        "text": "sudo: A password is required",
                
        "source": "Diagnosis: Occurs when a script or automated process attempts to use sudo without an interactive terminal (TTY) to prompt for a password. No TTY allocated."
                "Solution: Use the -S flag to pipe the password via stdin (echo $password | sudo -S /path/to/command) or (sudo -S /path/to/command < password.secret). This method is not recommended because a password can appear in logs and environment variables can be exposed. An alternate method is to configure /etc/sudoers file to allow specific commands without a password (E.g. myuser ALL=(ALL) NOPASSWD: /usr/local/bin/minio)."
                "Prevention: Always use passwordless sudo for specific commands in scripts by editing the sudoers file."
                "Error_type: Privilege escalation failure"
                "Severity: Medium - prevents command execution only when sudo requires authentication and no terminal is available."
                "Retrieved_sources: https://askubuntu.com/questions/1244898/sudo-a-terminal-is-required-to-read-the-password-either-use-the-s-option-to-r"
    },
    {
        "id": "err_005",
        "text": "<COMMAND>: command not found",
                
        "source": "Diagnosis: Occurs when the script or file that the system is trying to execute doesn't exist in the location specified by the PATH variable."
                "Solution: Execute the file directly using its absolute or relative path (e.g., ~/script or ./script), or add a new directory containing the command to the PATH variable (export PATH=$PATH:/path/to/directory). Also, make sure to install the missing package containing the command. Make sure there are no typos in the command using which command (which <command>)."
                "Prevention: Always place custom executables in directories included in the PATH (e.g., ~/.local/bin), add new directories to PATH via shell configuration files like .bashrc for persistent changes across all future sessions, and ensure required packages are installed before attempting to run their commands."
                "Error_type: Configuration error"
                "Severity: Medium - task fails, but system is not corrupted, and the fix is typically simple"
                "Retrieved_sources: https://www.redhat.com/en/blog/fix-command-not-found-error-linux"
    },
    {
        "id": "err_006",
        "text": "SSH operator: exit status = 127",
                
        "source": "Diagnosis: Indicates that the command was not found. This occurs when the system cannot locate the executable file in any of the paths defined by the PATH variable for the attempted command. "
                "Solution: Check that the command is typed correctly using the which command (which <command>). Check if the directory containing the command is included in the PATH variable (echo $PATH). If not, add it to PATH (export PATH=$PATH:/path/to/directory). Ensure that the required package providing the command is installed. Specify the full path to the command."
                "Prevention: Ensure the command or script exists and is executable by verifying its installation and path configuration before execution."
                "Error_type: Configuration error"
                "Severity: Medium - prevents command execution, but fix is typically straightforward and does not indicate deeper system issues."
                "Retrieved_sources: https://linuxconfig.org/how-to-fix-bash-127-error-return-code"
    },
    {
        "id": "err_007",
        "text": "No such file or directory: <file_path>",
                
        "source": "Diagnosis: The system cannot find the specified file or directory at the provided path. This can occur if the file was deleted, moved, or if there is a typo in the path. It can also happen if the script is being run from a different working directory than expected. Additionally, the file might require special permissions to access."
                "Solution:  Use absolute paths or ensure the script is run from the correct working directory. Check the exact path spelling. If the file is expected to be generated by a previous command, verify that command executed successfully."
                "Prevention: Always use absolute paths in scripts or ensure the working directory is correct. Implement error handling to check for file existence before attempting to access it."
                "Error_type: File system error "
                "Severity: Medium - prevents file access, but fix is typically straightforward and does not indicate deeper system issues."
                "Retrieved_sources: "
    },
    {
        "id": "err_008",
        "text": "Failed to enable unit: Unit file <FILE_NAME>.service does not exist",
                
        "source": "Diagnosis: The systemd service file for <FILE_NAME> is missing or not in the expected location. This occurs when the service was never installed, or the .service file is not placed in systemd directories (/etc/systemd/system/ or /lib/systemd/system/), or the filename is incorrect, or the installation step failed earlier"
                "Solution: Verify the service file exists (ls /etc/systemd/system/<FILE_NAME>.service). If missing, create or install the service. Reload the service (sudo systemctl daemon-reexec or sudo systemctl daemon-reload). Enable the service (sudo systemctl enable --now <FILE_NAME>)."
                "Prevention: Add a validation step to check if file exists before running systemctl enable."
                "Error_type: Configuration error"
                "Severity: Medium - prevents service startup but does not impact system stability"
                "Retrieved_sources: "
    },
    # ---Actual error logs for configuration of MinIO---
    {
        "id": "err_009",
        "text": "mc: <ERROR> Deprecated command. Please use 'mc admin policy attach'",
                
        "source": "Diagnosis: The mc admin policy set command is deprecated and has been replaced with mc policy admin attach in newer versions of the MinIO client."
                "Solution: Replace the deprecated command with the new syntax: {MC_BINARY} admin policy attach local (readwrite|readonly|writeonly) --user={MINIO_USER}. Replaces mc admin policy (set|unset|update) commands with mc admin policy (attach|detach)."
                "Prevention: Always check the MinIO client version and review changelogs when upgrading, or use mc --help to verify current command syntax before scripting."
                "Error_type:  Configuration error - using incorrect command syntax due to version mismatch or outdated script. "
                "Severity: Low - easily fixable by updating to the current command syntax."
                "Retrieved_sources: https://github.com/minio/mc/issues/4513, https://docs.min.io/enterprise/aistor-object-store/reference/cli/admin/mc-admin-policy/mc-admin-policy-attach/"
    },
    {
        "id": "err_010",
        "text": "mc: <ERROR> Unable to initialize new alias from the provided credentials. Get \"http://<IP_ADDRESS>:<PORT_NUMBER>/probe-bsign-<RANDOM_STRING>/?location=\": dial tcp 127.0.0.1:<PORT_NUMBER>:connect: connection refused",
                
        "source": "Diagnosis: MinIO client (mc) is unable to connect to the MinIO server at <IP_ADDRESS>:<PORT_NUMBER>. The connection is being actively refused, meaning no service is listening on that port. This could mean that the MinIO server is not running, or it is running on a different port, or MinIO crashed or failed to start."
                "Solution: Check if MinIO server is running: (ps aux | grep minio). Start MinIO if not running: (minio server /data --console-address ":9000"). Verify the correct port: (netstat -tuln | grep 9000). Port 9000 is the default port. Update mc alias with the correct endpoint."
                "Prevention: Always verify the correct MinIO API port (default 9000) before configuring aliases, and check that the server is actually running on that port."
                "Error_type:  Connection error "
                "Severity: Mediun - blocks all downstream MinIO operations."
                "Retrieved_sources: https://github.com/minio/minio/issues/13639#issuecomment-966244704"
    },
    {
        "id": "err_011",
        "text": "Command exited with return code 1",
                
        "source": "Diagnosis: This is a generic failure message. The exact cause can be found in earlier logs. "
                "Solution: Check earlier logs for ERRORS/Exception. Find the root cause and fix the underlying issue."
                "Prevention: Log detailed command output (stdout + stderr). Add explicit error messages in scripts."
                "Error_type: Execution error"
                "Severity: Medium - Task failed, but reason is not present in the error message itself"
                "Retrieved_sources: https://stackoverflow.com/questions/20965762/meaning-of-exit-status-1-returned-by-linux-command"
    },
    {
        "id": "err_012",
        "text": "Unable to find image 'minio/minio:<IMAGE_TAG>' locally",
                
        "source": "Diagnosis: Docker cannot find the specified image locally and is unable to pull it from the registry because the tag does not exist. The image tag is invalid or mistyped. Possible typo in repository or tag name."
                "Solution: Verify available images (docker images | grep minio). Build the image locally if source exists (docker build -t minio/minio:<CUSTOM_TAG>). Load image from tar file ifexported (docker load -i <MINIO_IMAGE>.tar)"
                "Prevention: Pre-build or pre-load images before deployment task. Use docker images to verify local availability before running containers. Implement a pre=check task that validates image eistence."
                "Error_type: Configuration error"
                "Severity: Medium - Container cannot start but the fix is straightforward. No system-wide damage"
                "Retrieved_sources: https://stackoverflow.com/questions/38464549/i-cant-find-my-docker-image-after-building-it"
    },
    {
        "id": "err_013",
        "text": "docker: Error response from daemon: manifest for minio/minio:<IMAGE_TAG> not found: manifest unknown: manifest unknown",
                
        "source": "Diagnosis: Docker successfully connected to Docker Hub but the registry returned a 404 error because the specified image tag does not exist in the remote repository. The image tag is misspelled or invalid. The tag may refer to a version that was never published. The image reposiroty name may be incorrect."
                "Solution: List all available tags (skopeo list-tags docker://minio/minio). Pull a valid tag (docker pull minio/minio:latest). Update command with the correct tag."
                "Prevention: Verify image tags exist before deployment. Implement a tag validation step."
                "Error_type: Configuration error"
                "Severity: Medium - Container cannot start but fix is straightforward. No system-wide damage."
                "Retrieved_sources: https://stackoverflow.com/questions/28320134/how-can-i-list-all-tags-for-a-docker-image-on-a-remote-registry, https://forums.docker.com/t/docker-error-response-from-daemon-manifest-not-found-when-running-container-following-get-started-tutorial/65107"
    },
    {
        "id": "err_014",
        "text": "SSH operator error: exit status = 125",
                
        "source": "Diagnosis: SSH operator executed a command on the remote host that failed with exit code 125, which in Docker contexts typically indicates a Docker daemon error such as invalid image reference, pull failure, or container creation issue."
                "Solution:  Check the full command output above the error to identify the specific failure. Correct accordingly."
                "Prevention: Use Docker operations with proper error handling. Log full command output to capture specific Docker errors."
                "Error_type: Runtime error"
                "Severity: Medium - Container cannot start, root cause is usually a configuration issue which requires manual investigation of commad output."
                "Retrieved_sources: https://komodor.com/learn/exit-codes-in-containers-and-kubernetes-the-complete-guide/"
    },
    {
        "id": "err_015",
        "text": "mc: <ERROR> invalid retention mode '<INVALIDMODE>'. Invalid arguments provided, please refer 'mc <command> -h' for relevant documentation.",
                
        "source": "Diagnosis: The mc client command failed because an invalid retention mode was specified. The MinIO retention policy requires valid modes such as governance or compliance. Invalid retention mode argument passed to mc retention set."
                "Solution:  Verify available retention modes (mc retention set --help). Check current retention settings (mc retention info <BUCKET_NAME>). Correct the retention mode to a valid value - governance or compliance."
                "Prevention: Validate retention mode arguments against allowed values (governance, compliance). Implement parameter checking before executing mc commands."
                "Error_type: Configuration error"
                "Severity: Low"
                "Retrieved_sources: https://docs.min.io/enterprise/aistor-object-store/reference/cli/mc-retention/mc-retention-info/"
    },
    {
        "id": "err_016",
        "text": "curl: (22) The requested URL returned error: 403",
                
        "source": "Diagnosis: The curl command attempted to access an endpoint that exists but returned an HTTP 403 Forbidden error, indicating the request was understood by the server but access is denied due to insufficient permissions.  Credentiasl were not provided, or the authenticated user does not have permission to access the endpoint."
                "Solution: Include authentication credentials, check available endpoints, or use a valid endpoint path."
                "Prevention: Verify endpoint paths before scripting. Test endpoints with valid credentials before automating. Always include authentication credentials when accessing protected endpoints."
                "Error_type: Authentication error"
                "Severity: Medium - Authentication or authorization issue, but does not affect system stability"
                "Retrieved_sources: "
    },
    {
        "id": "err_017",
        "text": "SSH operator error: exit status = 22",
                
        "source": "Diagnosis: The curl command-line tool often uses exit code 22 to indicate that the requested URL was not found (e.g., HTTP 404 error) on the server, but curl successfully connected and returned an error message in its output."
                "Solution: Examine the command output above the error to identify the specific failure. Verify command syntax and arguments. For HTTP-related errors, ensure URLs are correctly formatted and verify authentication credentials are included."
                "Prevention: Use proper error handling and logging to capture detailed failure reasons. Validate command arguments before execution in automation scripts."
                "Error_type: Runtime error"
                "Severity: Medium - Task fails with non-zero exit code which indicates syntax or parameter issue, but does not affect system stability"
                "Retrieved_sources: https://gist.github.com/gitkodak/b9c253e89397335356b13b37985778f5"
    },
    {
        "id": "err_018",
        "text": "mc: <ERROR> Unable to initialize new alias from the provided credentials. The request signature we calculated does not match the signature you provided. Check your key and signing method.",
                
        "source": "Diagnosis:  The mc client failed to authenticate with the MinIO server because the provided credentials were incorrect, the system time was out of sync, or the server was not ready to accept requests. The signature mismatch indicates the server rejected the authentication attempt. Root cause could be nncorrect access key or secret key, or client and server system time are out of sync (signature validation uses timestamps), MinIO server not fully initialized when mc command runs, URL endpoint or protocol mismatch (HTTP vs HTTPS), or special characters in keys misinterpreted by shell."
                "Solution: Check MinIO server credentials (docker exec minio_server env | grep MINIO_ROOT). Add a health check before alias creation (curl -s http://127.0.0.1:<PORT_NUMBER>/minio/health/live). Synchronize system time (sudo timedatecl set-ntp true; sudo ntpdate -u pool.ntp.org). Set alias with correct credentials (mc alias set local https://127.0.0.1:<PORT_NUMBER> <MINIO_ROOT_USER> <MINIO_ROOT_PASSWORD>). Use single quotes to prevent shell interpretation."
                "Prevention: Implement server health check before running mc commands. Use environment variables for credentials. Keep system time synchronized using NTP."
                "Error_type: Authentication error"
                "Severity: Medium - Authentication fails preventing all subsequent MinIO operations"
                "Retrieved_sources: https://drdroid.io/stack-diagnosis/minio-the-request-signature-we-calculated-does-not-match-the-signature-you-provided"
    },
    {
        "id": "err_019",
        "text": "mc: <ERROR> Unable to create new policy: invalid character ']' after object key:value pair.",
                
        "source": "Diagnosis: The system is trying to parse a JSON file. It encountered a ] where it expected more key:value content or a closing }. Likely causes are missing } to close an object, extra or misplaced ] or comma, incomplete key-value pair, or improper nesting of {} and []."
                "Solution: Use jq to show the exact line and column of error (jq . /path/to/policy.json). Fix the JSON structure (nano /path/to/policy.json). Validate the JSON structure (jq . /path/to/policy.json). Rerun the original command. "
                "Prevention: Always validate JSON before using it."
                "Error_type: Syntax error"
                "Severity: Low - Configuration is not applied, but does not crash services"
                "Retrieved_sources: https://jsonlint.com/json-syntax-error"
    },
    {
        "id": "err_020",
        "text": "syntax error: unexpected end of file",
                
        "source": "Diagnosis: Indicates that the interpreter reached the end of the file while it was still expecting an open syntactical construct to be closed. Likely causes are missing fi for an if block, missing done for a loop, unclosed quotes, uclosed braces {}, or incomplete multi-line command."
                "Solution: Inspect the file contents (cat /path/to/file). Open the file in an editor and fix the structure (nano /path/to/file). Revalidate using the relevant tools after fixing. Rerun the command."
                "Prevention: Always run syntax check before execution."
                "Error_type: Syntax error"
                "Severity: Low - Workflow is blocked, but no direct system damage"
                "Retrieved_sources: https://unix.stackexchange.com/questions/193165/syntax-error-unexpected-end-of-file-bash-script"
    },
    {
        "id": "err_021",
        "text": "req: Unknown option or message digest",
                
        "source": "Diagnosis: A command (usually openssl req) received an invalid argument. It either doesn't recognize an option/flag, or a message digest algorithm (like -sha256). Likely causes are typo in a flag, using an unsuppported digest algorithm, passing arguments in the wrong order, using a command incompatible with installed version of openssl"
                "Solution: Verify valid options for openssl (openssl req -help). Check supported message digests (openssl list -digest-algorithms). Fix the command. If issue persists, check openssl version (openssl version)"
                "Prevention: Always refer to help before using commands. Avoid typos in flags. Stick to widely supported digests."
                "Error_type: Configuration error"
                "Severity: Low - Task fails immediately, no system changes made"
                "Retrieved_sources: https://docs.openssl.org/3.6/man1/openssl-req/#options"
    },
    # --- Actual error logs for configuration of NFS ---
    {
        "id": "err_022",
        "text": "Error response from daemon: No such container: <CONTAINER_NAME>",
                
        "source": "Diagnosis: The Docker daemon cannot find a container with the given name or ID. The container either does not exist, was removed/stopped or was referenced incorrectly. Likely causes include typo in container name/ID, container was deleted, container hasn't been created yet, or trying to access a stopped container with wrong command."
                "Solution: List running containers (docker ps). List all containers including stopped (docker ps -a). Start container if it exists but is stopped (docker start <CONTAINER_NAME>). Re-run container if it was removed (docker run <IMAGE_NAME>). Double check the container name (docker ps -a --format "{{.Names}}")."
                "Prevention: Avoid losing containers unintentionally. Be careful with --rm flag. Check container status before operations (docker ps -a)."
                "Error_type: Runtime error"
                "Severity: Low - Container access is affected, but no system damage or data corruption."
                "Retrieved_sources: https://stackoverflow.com/questions/50323199/docker-error-no-such-container-friendlyhello, https://oneuptime.com/blog/post/2026-01-25-fix-docker-no-such-container-errors/view#:~:text=%22No%20such%20container%22%20errors%20typically,container%20existence%20before%20attempting%20operations."
    },
    {
        "id": "err_023",
        "text": "SSH comand timed out",
                
        "source": "Diagnosis: An SSH connection was attempted, but no response was received within the allowed time. Likely causes are target machine is down or unreachable, network issues (wrong IP, DNS failure, firewall blocking), SSH service not running on the remote machine, or a long-running command exceeding timeout limit."
                "Solution: Check is target machine is reachable over the network (ping <TARGET_MACHINE>). Check is port 22 for SSH is open (nc -zv <TARGET_MACHINE> 22). Try manual SSH with verbose output to see what is failing (ssh -vvv user@<TARGET_MACHINE>). Confirm if SSH server is active on the target machine (sudo systemctl status ssh). If needed, start SSH (sydo systemctl start ssh). Increase timeout of command is long-running (ssh -o ConnectTimeout=30 user@<TARGET_MACHINE>). Verify is SSH port 22 is allowed by the firewall (sudo ufw status). If blocked, allow it (sudo ufw allow 22)."
                "Prevention: Ensure SSH service is always running (sudo systemctl enable ssh). Avoid DNS or typo-related failures. Set appropriate timeouts in scripts. Configure proper firewall rules."
                "Error_type: Network error"
                "Severity: Medium - Blocks automation scripts, but no direct data/system damage"
                "Retrieved_sources: https://oneuptime.com/blog/post/2026-01-24-fix-ssh-connection-timeout-errors/view#:~:text=SSH%20connection%20timeouts%20are%20frustrating,and%20fix%20SSH%20connection%20timeouts."
    },
    {
        "id": "err_024",
        "text": "ERROR: nfs module is not loaded in the Docker host's kernel (try: modprobe nfs)",
                
        "source": "Diagnosis: The host system is trying to use NFS functionality, but the required kernel module (nfs) is not loaded. Docker (or another service) cannot access NFS-based storage without it. Likely causes are NFS kernel module not loaded, NFS support not installed on the system, insufficient privileges to load kernel modules, or running inside a minimal/stripped-down OS."
                "Solution: Try loading the NFS kernel module dynamically without reboot (sudo modprobe nfs). Verify the module is loaded (lsmod | grep nfs). Install NFS utilities if missing (sudo apt update && sudo apt install nfs-common). Retry command on target machine again."
                "Prevention: Ensure NFS module loads automatically on startup (echo "nfs" | sudo tee -a /etc/modules). Verify dependencies before deployment. Avoid minimal OS images without NFS support. Ensure proper privileges, because kernel module loading requires root access."
                "Error_type: Configuration error"
                "Severity: Medium - Blocks NFS-based storage usage but does not affect unrelated system functions"
                "Retrieved_sources: https://unix.stackexchange.com/questions/119725/fatal-module-nfs-not-found#:~:text=Sorted%20by:,kernel%20is%20already%20the%20latest."
    },
    {
        "id": "err_025",
        "text": "exportfs: /etc/exports: unknown keyword <UNKNOWN_KEYWORD>",
                
        "source": "Diagnosis: The exportfs command failed because the /etc/exports file contains an invalid NFS export option that is not recognized. NFS export options must be valid keywords such as rw, ro, sync, async, no_root_squash, etc. The parser failed while reading the file, so exports cannot be applied. Likely causes are typo in an export option, unsupported or invalid keyword, wrong syntax/format in /etc/exports, or mixing options from different NFS versions."
                "Solution: Inspect the current NFS exports configuration (cat /etc/exports). Look for unkown or misspelled options/incorrect syntax and edit the file (sudo nano /etc/exports). Validate exports configuration (sudo exportfs -ra). Restart NFS service if needed (sudo systemctl restart nfs-kernel-server)."
                "Prevention: Follow correct syntax strictly. Avoid unknown or unsupported options. Validate after every change (sudo exportfs -ra). Backup /etc/exports before making changes."
                "Error_type: Configuration error"
                "Severity: Medium -  NFS exports fail to load, shared directories become inaccessible but no direct system damage"
                "Retrieved_sources: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/5/html/deployment_guide/s1-nfs-server-config-exports"
    },
    # --- Actual error logs for OS validation ---
    {
        "id": "err_026",
        "text": "ping: <INVALID_HOSTNAME>: Name or service not known",
                
        "source": "Diagnosis: The system cannot resolve the provided hostname. It failed to convert the name to IP address using DNS or local resolution. Likely causes are typo in hostname, DNS server not configured or unreachable, no internet/network connectivity, missing or incorrect /etc/hosts entry, or using a service name that does not exist."
                "Solution: Test with a known valid domain (ping google.com). If it works, the original hostname is likely wrong. If it fails, there is no internet connectivity. Query DNS directly and try resolving the hostname to an IP (nslookup <HOSTNAME>). Check DNS configuration (cat /etc/resolv.conf). Add a temporary host entry if needed, which manually maps hostname to an IP (sudo nano /etc/hosts). Restart networking if DNS issue (sudo systemctl restart NetworkManager)."
                "Prevention: Verify hostnames before. Ensure DNS is configured properly by keeping valid namservers in /etc/resolv.conf. Use IP addressess for critical operations."
                "Error_type: Network error"
                "Severity: Medium - Network operations fail completely, but no direct system damage."
                "Retrieved_sources: https://oneuptime.com/blog/post/2026-03-02-how-to-fix-name-or-service-not-known-errors-on-ubuntu/view#:~:text=The%20error%20%22Name%20or%20service%20not%20known%22,configuration%2C%20a%20malfunctioning%20DNS%20server%2C%20incorrect%20/etc/nsswitch."
    },
    {
        "id": "err_027",
        "text": "Command exited with return code 2",
                
        "source": "Diagnosis: A command finished execution but returned a non-zero exit code, which indicates some kind of error. Specifically, exit code 2 usually indicates incorrect usage of a command, syntax error or invalid arguments, and sometimes a misconfiguration or missing file/option. Likely causes are wrong flags or parameters passed to a command, missing required arguments, tool-specific validation failure, or invalid file paths or inputs."
                "Solution: Rerun the command to see the real error message above this return code. Print the last exit code (echo $?). Check command usage/help (<COMMAND> --help). Ensure required files actually exist (ls -l /path/to/file)."
                "Prevention:  Always validate command syntax before running. Test commands incrementally."
                "Error_type: Runtime error"
                "Severity: Medium - indicates failure of a command which can break deployments, but no inherent system damage"
                "Retrieved_sources: https://askubuntu.com/questions/892604/what-is-the-meaning-of-exit-0-exit-1-and-exit-2-in-a-bash-script"
    },
    {
        "id": "err_028",
        "text": "df: unrecognized option '<OPTION>'",
                
        "source": "Diagnosis: The df command received a flag/option it does not support. The command-line parser does not recognize that argument. Likely causes are a typo in the option, using an option from a different OS, or running in a minimal environment where df supports fewer flags."
                "Solution: Check valid flags for the current df version (df --help). Try common valid options (df -h). Check df version (df --version). Install full utilities if needed (sudo apt update && sudo apt insall coreutils)."
                "Prevention: Always check command compatibility. Use portable options and stick to widely supported flags like -h,-k. Avoid copying commands from incompatible systems."
                "Error_type: Configuration error "
                "Severity: Low - Command execution fails, but fix is straightforward and no damage to system/data occurs"
                "Retrieved_sources: https://labex.io/tutorials/linux-how-to-understand-df-command-flags-431265"
    },
    {
        "id": "err_029",
        "text": "free: unrecognized option '<OPTION>'",
                
        "source": "Diagnosis: The free command recceived a flag it does not support. The command exists, but the environment's version does not recognize the option. Likely causes are typos in the option, using flags from another Linux version, running inside a minimal environment, incorrect flag syntax, or using an older version of free with limited features."
                "Solution: Check which version of free is being used (free --version). Display all valid flags for the current version of the free command (free --help). Try common valid options that work on most systems (free -h). Install full utilities if needed (sudo apt update && sudo apt install procps)."
                "Prevention: Check command options before use. Avoid copying commands blindly across different OSes. Use widely supported options like -m."
                "Error_type: Configuration error "
                "Severity: Low - Command execution fails, but fix is straightforward and no damage to system/data occurs"
                "Retrieved_sources: https://man7.org/linux/man-pages/man1/free.1.html"
    },
    {
        "id": "err_030",
        "text": "curl: Failed to connect to localhost port <PORT>: Connection refused",
                
        "source": "Diagnosis: The curl command failed because it could not establish a TCP connection to the specified host and port. The connection was actively refused by the target machine, indicating that no service is listening on the specified host and port, or a firewall is rejecting the connection. Likely causes are target service is not running, service is running on a different port, service crashed or exited, port is not exposed, or firewall rules are blocking the port."
                "Solution: Check if any service is listening on the port (ss -tuln | grep <PORT>). If nothing shows, no service is running on that port. Check whether the required service is running (ps aux | grep <SERVICE_NAME>). Start the service if not running. Verify that the service is configured to run on the expected port (cat config.yaml). If using Docker, confirm that the container is running and check port mapping."
                "Prevention: Always verify service is running before connecting; avoid blind curl requests. Use health checks to confirm service availability." 
                "Error_type: Network error"
                "Severity: Medium - Service is unreachable and pipelines are broken, but no system damage"
                "Retrieved_sources: https://oneuptime.com/blog/post/2026-01-24-fix-connection-refused-errors/view"
    },
    {
        "id": "err_031",
        "text": "Command exited with return code 7",
                
        "source": "Diagnosis: The command executed but failed with exit code 7. For curl commands, exit code 7 specifically indicates a failure to connect to the host (connection refused, host unreachable, or timeout). For other commands, exit code 7 may have different meanings depending on the application. Likely causes could be target service not running, wrong host or port, port is closed or not listening, or network/firewall restrictions."
                "Solution: Identify which command failed (history | tail -n 5). If using curl, retry with verbose output (curl -v http://<HOST>:<PORT>). Check if service is running (ss -tuln | grep <PORT>). Check connectivity to confirm network reachability (ping <HOST>). If using Docker, ensure container is running and check port mapping."
                "Prevention: Verify service before connecting. Use correct host and port. Confirm server readiness before requests."
                "Error_type: Network error"
                "Severity: Medium - Service is unreachable and pipelines are broken, but no system damage."
                "Retrieved_sources: https://www.quora.com/How-do-I-resolve-cURL-Error-7-couldnt-connect-to-host"
    },
    {
        "id": "err_032",
        "text": "touch: cannot touch '<FILE>': Permission denied",
                
        "source": "Diagnosis: The touch command tried to create or modify a file, but the OS denied permission for that operation. Likely causes are user does not have write permission in the directory, file or directory is owned by another user like root, attempting to write in a restricted location (e.g. /root, /etc), file exits but is read-only or running inside a container with limited privileges. For example, /sys is a read-only virtual filesystem (sysfs). Regular users do not have write permissions in /sys. Even with sudo, arbitrary file creation in /sys is not allowed as it represents kernel objects"
                "Solution: Check directory permissions to confirm whether write permission is present (ls -ld <DIRECTORY>). Check file ownership (ls -l <FILE>). Bypass permission restrictions if allowed by running the command as root (sudo touch <FILE>). Change permissions if ownership of the file is available (chmod u+w <FILE>). Change ownership of the file if needed (sudo chown $USER:$USER <FILE_OR_DIRECTORY>). Use a writable directory (touch ~/<FILE)."
                "Prevention: Work in user-owned directories. Check permissions before writing. Set correct permissions during setup."
                "Error_type: Permission error"
                "Severity: Medium - prevents file creation/modification, but no system damage"
                "Retrieved_sources: https://oneuptime.com/blog/post/2026-01-24-bash-permission-denied/view"
    },
    {
        "id": "err_033",
        "text": "Command exited with return code 3",
                
        "source": "Diagnosis: A command executed but returned exit code 3, indicating failure. The exact meaning depends on the specific command/tool. Likely causes are service or process is not running, invalid state for the requested operation, or configuration or runtime condition not satisfied. For systemctl is-active <SERVICE>m return code 3 means the service is inactive or does not exist."
                "Solution: Identify the command that failed (history | tail -n 5). Verify the correct service name (systemctl list-units --type=service --all). Check if the service exists in systemd (systemctl list-unit-files). Use correct service name. Install the service if needed (sudo apt update && sudo apt install <SERVICE>). Check the service status to get detailed information about why it might be inactive (systemctl status <SERVICE_NAME>)"
                "Prevention: Validate service existence before checking status. Use idempotent checks that handle missing services gracefully."
                "Error_type: Configuration error"
                "Severity: Low - easily fixed by using correct service name or installing the service, no system impact"
                "Retrieved_sources: https://man7.org/linux/man-pages/man1/systemctl.1.html"
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
