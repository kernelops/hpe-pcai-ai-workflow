import requests
import paramiko

# Test SSH connection to your worker node
def test_ssh_connection():
    # Get the worker node from backend
    try:
        response = requests.get("http://localhost:8000/nodes")
        nodes = response.json()
        
        if not nodes:
            print("❌ No worker nodes found in backend")
            return
        
        node = nodes[0]  # Get first node
        ip = node['ip']
        username = node['username']
        password = node['password']
        
        print(f"🔍 Testing SSH connection to: {ip}")
        print(f"👤 Username: {username}")
        print(f"🔑 Password: {'*' * len(password)}")
        
        # Test SSH connection
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            print("🔗 Connecting...")
            ssh.connect(ip, username=username, password=password, timeout=10)
            print("✅ SSH connection successful!")
            
            # Test hostname command
            print("🏷️ Running hostname command...")
            stdin, stdout, stderr = ssh.exec_command("hostname")
            hostname = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            
            if error:
                print(f"❌ Command error: {error}")
            else:
                print(f"✅ Hostname: {hostname}")
            
            # Test whoami command
            stdin, stdout, stderr = ssh.exec_command("whoami")
            whoami = stdout.read().decode().strip()
            print(f"✅ Current user: {whoami}")
            
            # Test date command
            stdin, stdout, stderr = ssh.exec_command("date")
            date = stdout.read().decode().strip()
            print(f"✅ Date: {date}")
            
            ssh.close()
            print("🔌 Connection closed")
            
        except paramiko.AuthenticationException:
            print("❌ Authentication failed - wrong username/password")
        except paramiko.SSHException as e:
            print(f"❌ SSH connection failed: {e}")
        except Exception as e:
            print(f"❌ Connection error: {e}")
            
    except Exception as e:
        print(f"❌ Error getting nodes: {e}")

if __name__ == "__main__":
    test_ssh_connection()
