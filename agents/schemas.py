from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ParsedLog:
    dag_id: Optional[str]
    task_id: Optional[str]
    error_type: str
    error_message: str
    exit_code: Optional[int]
    evidence_lines: List[str] = field(default_factory=list)
