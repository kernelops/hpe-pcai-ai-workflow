import requests
import httpx

# Test Airflow API connectivity and log fetching
def test_airflow_logs():
    # Airflow settings
    AIRFLOW_BASE_URL = "http://localhost:8080"
    AIRFLOW_USERNAME = "airflow"
    AIRFLOW_PASSWORD = "airflow"
    DAG_ID = "deployment_workflow"
    
    print("🔍 Testing Airflow API connectivity...")
    
    # Test basic connectivity
    try:
        with httpx.Client(
            base_url=AIRFLOW_BASE_URL.rstrip("/"),
            auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD)
        ) as client:
            # Test basic API access
            resp = client.get("/api/v1/dags")
            if resp.is_success:
                print("✅ Airflow API accessible")
            else:
                print(f"❌ Airflow API failed: {resp.status_code} {resp.text}")
                return
    except Exception as e:
        print(f"❌ Cannot connect to Airflow: {e}")
        return
    
    # Get latest DAG run
    try:
        with httpx.Client(
            base_url=AIRFLOW_BASE_URL.rstrip("/"),
            auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD)
        ) as client:
            # Get DAG runs
            resp = client.get(f"/api/v1/dags/{DAG_ID}/dagRuns?order_by=-start_date&limit=1")
            if resp.is_success:
                runs = resp.json()
                if runs.get("dag_runs"):
                    latest_run = runs["dag_runs"][0]
                    run_id = latest_run["dag_run_id"]
                    print(f"✅ Found latest run: {run_id}")
                    print(f"   State: {latest_run.get('state', 'unknown')}")
                    
                    # Test task instance fetching
                    task_ids = ["get_worker_nodes", "create_airflow_connections", "run_hostname__0"]
                    
                    for task_id in task_ids:
                        try:
                            ti_resp = client.get(
                                f"/api/v1/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}"
                            )
                            if ti_resp.is_success:
                                ti_data = ti_resp.json()
                                state = ti_data.get("state", "unknown")
                                print(f"✅ Task {task_id}: {state}")
                                
                                # Test log fetching
                                log_resp = client.get(
                                    f"/api/v1/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances/{task_id}/logs/1"
                                )
                                if log_resp.is_success:
                                    content_type = log_resp.headers.get("Content-Type", "")
                                    if "application/json" in content_type:
                                        log_data = log_resp.json()
                                        log_content = log_data.get("content", str(log_data))
                                    else:
                                        log_content = log_resp.text
                                    
                                    if log_content.strip():
                                        print(f"✅ Logs found for {task_id}")
                                        print(f"   Preview: {log_content[:100]}...")
                                    else:
                                        print(f"⚠️  No logs for {task_id}")
                                else:
                                    print(f"❌ Log fetch failed for {task_id}: {log_resp.status_code}")
                            else:
                                print(f"❌ Task {task_id} not found: {ti_resp.status_code}")
                        except Exception as e:
                            print(f"❌ Error with task {task_id}: {e}")
                else:
                    print("❌ No DAG runs found")
            else:
                print(f"❌ Failed to get DAG runs: {resp.status_code}")
    except Exception as e:
        print(f"❌ Error testing logs: {e}")

if __name__ == "__main__":
    test_airflow_logs()
