# api/worker.py
import time
from common.models import TaskFailure

def process_log(**kwargs):
    """
    Background worker task for processing HPC error logs.
    In a real environment, this would trigger the LangGraph pipeline asynchronously.
    For this simulation, we simulate processing delay.
    """
    task_id = kwargs.get("failed_task", "unknown")
    print(f"[Worker] 📥 Received error log for task: {task_id}")
    
    # Simulate processing time
    time.sleep(2)
    
    print(f"[Worker] ✅ Processed log for task: {task_id}")
    return {"status": "processed", "task_id": task_id}
