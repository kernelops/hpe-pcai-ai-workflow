#!/usr/bin/env python3
"""
Setup script to configure Airflow SSH connections for worker nodes.
This script fetches worker nodes from the backend and creates corresponding SSH connections in Airflow.
"""

import requests
import subprocess
import sys
from datetime import datetime

def get_worker_nodes(api_base="http://localhost:8000"):
    """Fetch worker nodes from the backend API."""
    try:
        response = requests.get(f"{api_base}/nodes")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching worker nodes: {e}")
        return []

def create_airflow_ssh_connection(node_ip, username, password):
    """Create an SSH connection in Airflow for a worker node."""
    conn_id = f"worker_node_{node_ip.replace('.', '_')}"
    
    # Use Airflow CLI to create connection
    cmd = [
        "airflow", "connections", "add", conn_id,
        "--conn-type", "ssh",
        "--conn-host", node_ip,
        "--conn-login", username,
        "--conn-password", password,
        "--conn-port", "22",
        "--conn-description", f"SSH connection to worker node {node_ip}"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✓ Created SSH connection: {conn_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create connection {conn_id}: {e}")
        print(f"Error output: {e.stderr}")
        return False

def update_airflow_ssh_connection(node_ip, username, password):
    """Update an existing SSH connection in Airflow."""
    conn_id = f"worker_node_{node_ip.replace('.', '_')}"
    
    # Delete existing connection first
    delete_cmd = ["airflow", "connections", "delete", conn_id, "--yes"]
    try:
        subprocess.run(delete_cmd, capture_output=True, text=True, check=False)
    except:
        pass  # Connection might not exist
    
    # Create new connection
    return create_airflow_ssh_connection(node_ip, username, password)

def main():
    """Main setup function."""
    print("🚀 Setting up Airflow SSH connections for worker nodes...")
    print(f"⏰ {datetime.now()}")
    
    # Get worker nodes from backend
    nodes = get_worker_nodes()
    if not nodes:
        print("❌ No worker nodes found. Please add worker nodes first.")
        sys.exit(1)
    
    # Filter reachable nodes
    reachable_nodes = [node for node in nodes if node.get('status') == 'reachable']
    if not reachable_nodes:
        print("❌ No reachable worker nodes found.")
        print("Available nodes:")
        for node in nodes:
            print(f"  - {node['ip']}: {node.get('status', 'unknown')}")
        sys.exit(1)
    
    print(f"📋 Found {len(reachable_nodes)} reachable worker nodes:")
    for node in reachable_nodes:
        print(f"  - {node['ip']} ({node['username']})")
    
    # Setup SSH connections
    success_count = 0
    for node in reachable_nodes:
        print(f"\n🔧 Setting up connection for {node['ip']}...")
        if create_airflow_ssh_connection(node['ip'], node['username'], node['password']):
            success_count += 1
        else:
            # Try updating instead
            if update_airflow_ssh_connection(node['ip'], node['username'], node['password']):
                success_count += 1
    
    print(f"\n✅ Setup complete! {success_count}/{len(reachable_nodes)} connections configured.")
    
    # Test connections
    print("\n🧪 Testing SSH connections...")
    for node in reachable_nodes:
        conn_id = f"worker_node_{node['ip'].replace('.', '_')}"
        test_cmd = ["airflow", "connections", "test", conn_id]
        try:
            result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"✓ {node['ip']}: Connection successful")
            else:
                print(f"✗ {node['ip']}: Connection failed")
                print(f"  Error: {result.stderr}")
        except subprocess.TimeoutExpired:
            print(f"⏱ {node['ip']}: Connection timeout")
        except Exception as e:
            print(f"✗ {node['ip']}: Test error - {e}")
    
    print("\n🎉 Airflow SSH connections setup complete!")
    print("You can now trigger the deployment_workflow DAG to deploy to your worker nodes.")

if __name__ == "__main__":
    main()
