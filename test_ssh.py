import paramiko
import sys
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect("192.168.56.102", username="kernelops", password="password123", timeout=5)
    print("Connected with password123")
except Exception as e:
    print(f"password123 failed: {e}")
    try:
        client.connect("192.168.56.102", username="kernelops", password="kernelops", timeout=5)
        print("Connected with kernelops")
    except Exception as e:
        print(f"kernelops failed: {e}")

stdin, stdout, stderr = client.exec_command("sudo -n id", get_pty=True)
print("sudo -n id:", stdout.read().decode())
print("stderr:", stderr.read().decode())

stdin, stdout, stderr = client.exec_command("sudo id", get_pty=True)
stdin.write("kernelops\n")
stdin.flush()
print("sudo id with password written:", stdout.read().decode())
