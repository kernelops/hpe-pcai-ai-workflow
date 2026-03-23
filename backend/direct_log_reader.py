import os
import platform
import threading
import time
from pathlib import Path
from typing import Dict


class DirectLogReader:
    def __init__(self, logs_path: str = None):
        # Auto-detect logs path based on platform
        if logs_path is None:
            env_logs_path = os.getenv("AIRFLOW_LOGS_PATH")
            if env_logs_path:
                logs_path = env_logs_path
            else:
                # Project-local Airflow logs (repo/airflow/logs) should be preferred.
                project_logs = Path(__file__).resolve().parents[1] / "airflow" / "logs"
                if project_logs.exists():
                    logs_path = str(project_logs)

        if logs_path is None:
            if platform.system() == "Windows":
                possible_paths = [
                    "C:\\airflow\\logs",
                    "C:\\opt\\airflow\\logs",
                    "D:\\airflow\\logs",
                    "/opt/airflow/logs",  # Docker fallback
                ]
                logs_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        logs_path = path
                        break
                if logs_path is None:
                    logs_path = "C:\\airflow\\logs"
            else:
                logs_path = "/opt/airflow/logs"

        self.logs_path = Path(logs_path)
        self.current_logs: Dict[str, str] = {}
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.dag_id = None
        self.run_id = None

        print(f"DirectLogReader initialized with path: {self.logs_path}")

        if not self.logs_path.exists():
            print(f"Warning: log path does not exist: {self.logs_path}")
        else:
            print(f"Log path found: {self.logs_path}")

    def start_monitoring(self, dag_id: str, run_id: str):
        """Start monitoring logs for a specific DAG run."""
        if self.running:
            self.stop_monitoring()

        with self.lock:
            self.current_logs = {}

        self.running = True
        self.dag_id = dag_id
        self.run_id = run_id
        self.thread = threading.Thread(target=self._monitor_logs, daemon=True)
        self.thread.start()
        print(f"Started monitoring logs for {dag_id}/{run_id}")

    def stop_monitoring(self):
        """Stop monitoring logs."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        print("Stopped monitoring logs")

    def _normalize(self, value: str) -> str:
        return "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", ".", "+"})

    def _find_run_path(self, dag_id: str, run_id: str) -> Path | None:
        candidates = [
            self.logs_path / dag_id / run_id,  # legacy
            self.logs_path / f"dag_id={dag_id}" / f"run_id={run_id}",  # airflow 2.9 style
        ]
        for path in candidates:
            if path.exists():
                return path

        dag_dir_candidates = [self.logs_path / f"dag_id={dag_id}", self.logs_path / dag_id]
        normalized_run_id = self._normalize(run_id)
        for dag_dir in dag_dir_candidates:
            if not dag_dir.exists():
                continue
            for child in dag_dir.iterdir():
                if not child.is_dir():
                    continue
                child_name = child.name.removeprefix("run_id=")
                if self._normalize(child_name) == normalized_run_id:
                    return child
        return None

    def _collect_run_logs(self, run_path: Path) -> Dict[str, str]:
        logs: Dict[str, str] = {}
        try:
            for log_file in run_path.rglob("*.log"):
                stream_key = self._extract_stream_key(log_file, run_path)
                content = self._read_new_content(log_file, 0)
                if not content:
                    continue
                if stream_key not in logs:
                    logs[stream_key] = ""
                logs[stream_key] += content
        except Exception as exc:
            print(f"Error collecting logs for {run_path}: {exc}")
        return logs

    def get_combined_logs_for_run(self, dag_id: str, run_id: str) -> tuple[str, int]:
        run_path = self._find_run_path(dag_id, run_id)
        if not run_path:
            return "", 0
        run_logs = self._collect_run_logs(run_path)
        sections = []
        for stream_key, content in sorted(run_logs.items()):
            if not content or not content.strip():
                continue
            sections.append(f"===== {stream_key} =====\n{content.rstrip()}")
        return "\n\n".join(sections), len(run_logs)

    def _monitor_logs(self):
        """Monitor log files in real-time."""
        dag_logs_path = self._find_run_path(self.dag_id, self.run_id)
        if dag_logs_path is None:
            dag_logs_path = self.logs_path / self.dag_id / self.run_id
        print(f"Watching log directory: {dag_logs_path}")

        file_positions: Dict[str, int] = {}

        wait_count = 0
        while not dag_logs_path.exists() and wait_count < 30 and self.running:
            print(f"Waiting for log directory... ({wait_count}/30)")
            time.sleep(1)
            wait_count += 1

        if not dag_logs_path.exists():
            resolved_path = self._find_run_path(self.dag_id, self.run_id)
            if resolved_path:
                dag_logs_path = resolved_path
                print(f"Found log directory via fallback: {dag_logs_path}")
            else:
                print(f"Log directory not found: {dag_logs_path}")
                return

        print(f"Found log directory: {dag_logs_path}")

        while self.running:
            try:
                log_files = list(dag_logs_path.rglob("*.log"))

                for log_file in log_files:
                    stream_key = self._extract_stream_key(log_file, dag_logs_path)
                    position_key = str(log_file)
                    new_content = self._read_new_content(log_file, file_positions.get(position_key, 0))

                    if not new_content:
                        continue

                    with self.lock:
                        if stream_key not in self.current_logs:
                            self.current_logs[stream_key] = ""
                        self.current_logs[stream_key] += new_content

                    file_positions[position_key] = log_file.stat().st_size

                time.sleep(1)
            except Exception as e:
                print(f"Error monitoring logs: {e}")
                time.sleep(2)

    def _extract_stream_key(self, log_file: Path, run_path: Path) -> str:
        """
        Extract stable stream key from log path.
        Supports both regular and mapped task directory structures.
        """
        try:
            relative_parts = log_file.relative_to(run_path).parts
            if len(relative_parts) <= 1:
                return log_file.stem
            return "/".join(relative_parts[:-1])
        except Exception:
            return log_file.parent.name

    def _read_new_content(self, log_file: Path, last_position: int) -> str:
        """Read new content from log file since last position."""
        try:
            current_size = log_file.stat().st_size
            if current_size <= last_position:
                return ""

            with open(log_file, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(last_position)
                return handle.read()
        except Exception as e:
            print(f"Error reading {log_file}: {e}")
            return ""

    def get_logs(self, task_id: str) -> str:
        """Get logs for one task and mapped variants."""
        with self.lock:
            chunks = []
            for stream_key in sorted(self.current_logs.keys()):
                if stream_key == task_id or stream_key.startswith(f"{task_id}/"):
                    chunks.append(self.current_logs[stream_key])
        return "\n".join(chunks)

    def get_all_logs(self) -> Dict[str, str]:
        """Get all collected logs keyed by task stream."""
        with self.lock:
            return self.current_logs.copy()

    def get_combined_logs(self) -> str:
        """Get all logs as a single formatted stream."""
        with self.lock:
            items = sorted(self.current_logs.items())

        sections = []
        for stream_key, content in items:
            if not content or not content.strip():
                continue
            sections.append(f"===== {stream_key} =====\n{content.rstrip()}")

        return "\n\n".join(sections)


# Global log reader instance
log_reader = DirectLogReader()
