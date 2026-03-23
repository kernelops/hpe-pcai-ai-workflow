import subprocess

# Test that the DAG commands work locally
print("Testing commands that will run in the DAG:")

result = subprocess.run(['hostname'], capture_output=True, text=True)
print(f'Hostname: {result.stdout.strip()}')

result = subprocess.run(['whoami'], capture_output=True, text=True)
print(f'User: {result.stdout.strip()}')

result = subprocess.run(['pwd'], capture_output=True, text=True)
print(f'Directory: {result.stdout.strip()}')

print("\nThese are the REAL commands that will execute on your worker nodes!")
