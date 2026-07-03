import paramiko
import time

def run_cmd(ip, username, password, command):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=username, password=password, timeout=5)
   
    if "sudo" in command:
        stdin, stdout, stderr = client.exec_command(command, get_pty=True)
    else:
        stdin, stdout, stderr = client.exec_command(command)        

    stdout.channel.settimeout(60)
    
    if "sudo" in command and password:
        stdin.write(password + "\n")
        stdin.flush()
        time.sleep(0.5)
        
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace").strip()
    output = output.replace(password, "")
    
    if "[sudo] password for" in output:
        lines = output.split("\n")
        lines = [l for l in lines if not l.startswith("[sudo] password for") and l.strip() != password and not l.strip() == ""]

        output = "\n".join(lines).strip()
        
    print(f"[{command}] EXIT: {exit_code}")
    print(f"OUT: {output}")
    print(f"ERR: {stderr.read().decode() if 'sudo' not in command else ''}")

run_cmd("192.168.1.5", "kali", "kali", "which minio")
run_cmd("192.168.1.5", "kali", "kali", "which mc")
run_cmd("192.168.1.5", "kali", "kali", "ps aux | grep -v grep | grep minio")
run_cmd("192.168.1.5", "kali", "kali", "sudo systemctl is-active minio")
run_cmd("192.168.1.5", "kali", "kali", "sudo systemctl status minio --no-pager")
run_cmd("192.168.1.5", "kali", "kali", "ss -tuln | grep 9000")
run_cmd("192.168.1.5", "kali", "kali", "ss -tuln | grep -E '900[0-9]'")
run_cmd("192.168.1.5", "kali", "kali", "sudo ufw status")
run_cmd("192.168.1.5", "kali", "kali", "sudo iptables -L INPUT -n | grep 9000")

