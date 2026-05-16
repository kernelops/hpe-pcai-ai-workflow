import paramiko
import time

def run_cmd(ip, username, password, command):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=username, password=password, timeout=5)
    
    kwargs = {"timeout": 15}
    if "sudo" in command:
        kwargs["get_pty"] = True
        
    stdin, stdout, stderr = client.exec_command(command, **kwargs)
    
    if "sudo" in command and password:
        stdin.write(password + "\n")
        stdin.flush()
        time.sleep(0.5)
        
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace").strip()
    
    if "[sudo] password for" in output:
        lines = output.split("\n")
        lines = [l for l in lines if not l.startswith("[sudo] password for") and not l.strip().endswith(password)]
        output = "\n".join(lines).strip()
        
    print(f"[{command}] EXIT: {exit_code}")
    print(f"OUT: {output}")
    print(f"ERR: {stderr.read().decode() if not kwargs.get('get_pty') else ''}")

# Let's test with the node 192.168.29.7 if possible? Wait, 192.168.29.7 is my laptop's IP!
run_cmd("127.0.0.1", "kernelops", "230105", "sudo id")
run_cmd("127.0.0.1", "kernelops", "230105", "sudo systemctl list-unit-files | grep minio || true")
