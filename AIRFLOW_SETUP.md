# Airflow + Worker Nodes Setup Guide

This guide shows how to configure Airflow to use your worker nodes for deployment.

## 🎯 How It Works

**Flow:**
```
Frontend → Backend → Airflow API → Airflow DAG → SSH to Your Worker Nodes
```

1. **Backend** passes worker node credentials to Airflow
2. **Airflow DAG** creates SSH connections to your nodes
3. **SSH Operators** execute commands on your actual servers
4. **Real-time logs** show output from your worker nodes

## 📋 Prerequisites

### 1. Airflow Installation
```bash
# Install Airflow with SSH provider
pip install apache-airflow[ssh,celery,redis]
pip install apache-airflow-providers-ssh
```

### 2. Airflow Configuration
Make sure your `airflow.cfg` has:
```ini
[core]
enable_xcom_pickling = True

[ssh]
# SSH connection settings
```

## 🚀 Setup Steps

### Step 1: Start Airflow
```bash
# Initialize Airflow database
airflow db init

# Start Airflow webserver
airflow webserver -p 8080

# Start Airflow scheduler (in another terminal)
airflow scheduler
```

### Step 2: Setup SSH Connections
Run the setup script to configure SSH connections for your worker nodes:

```bash
python setup_airflow_connections.py
```

This script will:
- Fetch worker nodes from your backend API
- Create SSH connections in Airflow for each node
- Test the connections

### Step 3: Verify Airflow Connections
```bash
# List all connections
airflow connections list

# Test a specific connection
airflow connections test worker_node_192_168_1_100
```

### Step 4: Update Airflow DAG
The DAG at `airflow/dags/deployment_workflow.py` will:

1. **Fetch worker nodes** from your backend API
2. **Create SSH connections** dynamically
3. **Execute deployment tasks** on each node:
   - System update
   - Docker installation
   - Firewall configuration
   - Application deployment
   - Health check

## 🔧 Manual SSH Connection Setup

If the script doesn't work, you can set up connections manually:

### Option A: Using Airflow CLI
```bash
# For each worker node:
airflow connections add worker_node_192_168_1_100 \
    --conn-type ssh \
    --conn-host 192.168.1.100 \
    --conn-login root \
    --conn-password your_password \
    --conn-port 22 \
    --conn-description "SSH to worker node 192.168.1.100"
```

### Option B: Using Airflow UI
1. Go to http://localhost:8080
2. Navigate to **Admin** → **Connections**
3. Click **+ Add a new record**
4. Fill in:
   - **Connection Id**: `worker_node_192_168_1_100`
   - **Connection Type**: `SSH`
   - **Host**: `192.168.1.100`
   - **Username**: `root`
   - **Password**: `your_password`
   - **Port**: `22`

## 📊 What Happens During Deployment

### When You Click "Start Deployment":

1. **Backend** gets all reachable worker nodes
2. **Backend** triggers Airflow DAG with node credentials
3. **Airflow** creates SSH connections to each node
4. **DAG Tasks** execute in sequence:
   ```
   get_worker_nodes → deploy_to_all_nodes → check_node → update_system → install_docker → deploy_app → health_check
   ```

5. **SSH Operators** run commands on your actual servers:
   ```bash
   # On 192.168.1.100:
   sudo apt update && sudo apt upgrade -y
   curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
   sudo docker run -d --name myapp -p 80:80 nginx:latest
   
   # On 192.168.1.101:
   sudo apt update && sudo apt upgrade -y
   curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
   sudo docker run -d --name myapp -p 80:80 nginx:latest
   
   # And so on for each node...
   ```

## 🎛 Monitoring Deployment

### In Airflow UI:
- Go to http://localhost:8080
- Navigate to **DAGs** → **deployment_workflow**
- Click on the DAG run to see:
  - Task status per node
  - Logs from each SSH command
  - Execution timeline

### In Your Frontend:
- Real-time status updates
- Consolidated logs from all nodes
- Success/failure indicators

## 🔍 Troubleshooting

### SSH Connection Issues
```bash
# Test SSH connection manually
ssh root@192.168.1.100

# Check Airflow connection
airflow connections test worker_node_192_168_1_100
```

### Common Problems:
1. **SSH Key Authentication**: If using SSH keys instead of passwords:
   ```bash
   airflow connections add worker_node_192_168_1_100 \
       --conn-type ssh \
       --conn-host 192.168.1.100 \
       --conn-login root \
       --conn-extra '{"key_file": "/path/to/private/key"}'
   ```

2. **Firewall Issues**: Ensure SSH port (22) is open on worker nodes

3. **Permission Issues**: Make sure the user has sudo privileges

4. **Airflow Provider**: Ensure SSH provider is installed:
   ```bash
   pip install apache-airflow-providers-ssh
   ```

## 🎉 Benefits of This Approach

1. **Airflow Orchestration**: Professional workflow management
2. **Real Worker Nodes**: Commands execute on your actual servers
3. **Scalable**: Add more nodes = more deployment capacity
4. **Monitoring**: Airflow UI provides detailed execution tracking
5. **Retry Logic**: Automatic retry on failures
6. **Logging**: Centralized logs from all nodes

## 📝 Next Steps

1. **Start Airflow**: `airflow webserver -p 8080`
2. **Run Setup Script**: `python setup_airflow_connections.py`
3. **Add Worker Nodes** in the frontend
4. **Test Deployment** from the UI
5. **Monitor** in Airflow DAG view

Your Airflow system will now actually use your worker nodes for deployment! 🚀
