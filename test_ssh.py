import paramiko
import sys
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect("192.168.1.5", username="kali", password="kali", timeout=5)
    print("Connected with kali")
except Exception as e:
    print(f"kali failed: {e}")

stdin, stdout, stderr = client.exec_command("sudo -n id", get_pty=True)
print("sudo -n id:", stdout.read().decode())
print("stderr:", stderr.read().decode())

stdin, stdout, stderr = client.exec_command("sudo id", get_pty=True)
stdin.write("kali\n")
stdin.flush()
print("sudo id with password written:", stdout.read().decode())
