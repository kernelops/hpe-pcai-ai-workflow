import socket
import subprocess
import platform

node_ip = '128.168.1.5'
print(f'Testing connectivity to {node_ip}...')

# Test 1: Ping
try:
    if platform.system().lower() == 'windows':
        cmd = ['ping', '-n', '1', '-w', '2000', node_ip]
    else:
        cmd = ['ping', '-c', '1', '-W', '2', node_ip]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f'✓ Ping successful to {node_ip}')
    else:
        print(f'⚠ Ping failed to {node_ip}: {result.stderr[:100]}')
except Exception as e:
    print(f'⚠ Ping check failed: {e}')

# Test 2: SSH to port 22
ssh_success = False
try:
    print(f'Attempting SSH connection to {node_ip}:22...')
    with socket.create_connection((node_ip, 22), timeout=5):
        print(f'✓ SSH connection successful to {node_ip}:22')
        ssh_success = True
except socket.timeout:
    print(f'⚠ SSH timeout to {node_ip}:22')
except ConnectionRefusedError:
    print(f'⚠ SSH connection refused by {node_ip}:22')
except OSError as e:
    print(f'⚠ SSH network error to {node_ip}: {e}')
except Exception as e:
    print(f'⚠ SSH unexpected error to {node_ip}: {e}')

# Test 3: Alternative ports
alt_port_success = False
if not ssh_success:
    common_ports = [2222, 2022, 2020]
    for port in common_ports:
        try:
            print(f'Trying alternative port {node_ip}:{port}...')
            with socket.create_connection((node_ip, port), timeout=3):
                print(f'✓ Found SSH on alternative port {port}')
                alt_port_success = True
                break
        except:
            continue

print(f'Final result: Ping={result.returncode == 0}, SSH={ssh_success}, Alt_Port={alt_port_success}')
