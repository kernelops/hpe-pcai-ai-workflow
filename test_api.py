import requests
import json

# Test adding a worker node
url = "http://localhost:8000/nodes"
headers = {"Content-Type": "application/json"}
data = {
    "ip": "127.0.0.1",
    "username": "test",
    "password": "test"
}

try:
    print("Testing POST to /nodes...")
    response = requests.post(url, json=data, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        print("✓ Node added successfully!")
        node_data = response.json()
        print(f"Node details: {node_data}")
    else:
        print(f"✗ Failed to add node. Status: {response.status_code}")
        
except Exception as e:
    print(f"Error: {e}")

# Test getting nodes
try:
    print("\nTesting GET to /nodes...")
    response = requests.get("http://localhost:8000/nodes")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
