import requests

# Test adding a local reachable node
response = requests.post('http://localhost:8000/nodes', json={
    'ip': '127.0.0.1',
    'username': 'test', 
    'password': 'test'
})

print(f'Status: {response.status_code}')
print(f'Response: {response.json()}')

# Test getting nodes
response = requests.get('http://localhost:8000/nodes')
print(f'Nodes list: {response.json()}')
