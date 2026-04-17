import api.main
from common.models import TaskFailure

f = TaskFailure(
    dag_run_id='123',
    task_id='configure_access_policies',
    state='failed',
    log_text='airflow.exceptions.AirflowException: SSH operator error: exit status = 1',
    timestamp='123'
)

res = api.main._log.analyse(f)
print("D:", res.rag_diagnosis)
print("S:", res.rag_solution)
