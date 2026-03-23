# agents/log_analyser_agent.py
import json
import requests
from groq import Groq
from common.config import GROQ_API_KEY, GROQ_MODEL, RAG_API_URL
from common.models import TaskFailure, ErrorReport

class LogAnalyserAgent:
    """
    Analyses Airflow task logs using LLM.
    If RAG API is available, enriches context first.
    Works standalone with LLM only when RAG is not ready.
    """
    def __init__(self):
        self.client  = Groq(api_key=GROQ_API_KEY)
        self.use_rag = bool(RAG_API_URL)

    def _get_rag_context(self, log_text: str) -> str:
        """Call RAG API if available. Returns empty string if not."""
        if not self.use_rag:
            return ""
        try:
            r = requests.post(f"{RAG_API_URL}/analyze",
                              json={"log_text": log_text}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return (f"RAG Context:\n"
                        f"Diagnosis: {data.get('diagnosis', '')}\n"
                        f"Solution hints: {data.get('solution', '')}\n"
                        f"Similar errors: "
                        f"{', '.join(data.get('retrieved_sources', []))}")
        except Exception as e:
            print(f"[LogAnalyser] RAG unavailable, using LLM only: {e}")
        return ""

    def analyse(self, failure: TaskFailure) -> ErrorReport:
        print(f"[LogAnalyser] 🔍 Analysing log for task: {failure.task_id}")

        rag_context = self._get_rag_context(failure.log_text)
        rag_section = f"\n\nAdditional context from knowledge base:\n{rag_context}" \
                      if rag_context else ""

        prompt = f"""You are an expert HPE PCAI infrastructure engineer analysing 
an Airflow deployment task failure.

Failed Task: {failure.task_id}
Task State: {failure.state}
Timestamp: {failure.timestamp}

Raw Log:
{failure.log_text}
{rag_section}

Analyse this log and respond with ONLY valid JSON in this exact format:
{{
    "error_type": "short error class name e.g. S3Error, ConnectionError, etc",
    "error_message": "the exact error message from the log",
    "error_line": "file path and line number where error occurred if visible",
    "diagnosis": "clear 1-2 sentence explanation of what went wrong",
    "confidence": 0.0 to 1.0 float indicating your confidence
}}"""

        response = self.client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown code blocks if LLM wraps in them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        parsed = json.loads(raw.strip())

        report = ErrorReport(
            task_id      = failure.task_id,
            error_type   = parsed["error_type"],
            error_message= parsed["error_message"],
            error_line   = parsed.get("error_line"),
            diagnosis    = parsed["diagnosis"],
            confidence   = float(parsed["confidence"]),
            raw_log      = failure.log_text
        )

        print(f"[LogAnalyser] ✅ Error identified: {report.error_type} "
              f"(confidence: {report.confidence})")
        return report
