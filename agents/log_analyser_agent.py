# agents/log_analyser_agent.py
import json
import re
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
        self.client  = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        self.use_rag = bool(RAG_API_URL)

    def _get_rag_analysis(self, failure: TaskFailure) -> dict:
        """Call RAG API if available. Returns empty dict if not."""
        if not self.use_rag:
            return {}
        try:
            print(f"log_text: {failure.log_text}")
            print(f"task_id: {failure.task_id}")
            r = requests.post(f"{RAG_API_URL}/analyze",
                              json={
                                  "log_text": failure.log_text,
                                  "task_id": failure.task_id,
                              }, timeout=10)
            if r.status_code == 200:
                print(f"RAG ANALYSIS: {r.json()}")
                return r.json()
            else:
                print(f"[LogAnalyser] RAG API error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[LogAnalyser] RAG unavailable, using LLM only: {e}")
        return {}

    def _format_rag_context(self, rag_analysis: dict) -> str:
        if not rag_analysis or not rag_analysis.get("matches"):
            return ""
        
        sections = []
        
        # Group by field
        diagnoses = []
        solutions = []
        preventions = []
        error_types = []
        severities = []
        sources = set()
        
        for match in rag_analysis["matches"]:
            matched_line = match.get("matched_line", "")
            diagnosis = match.get("diagnosis", "").strip()
            solution = match.get("solution", "").strip()
            prevention = match.get("prevention", "").strip()
            error_type = match.get("error_type", "").strip()
            severity = match.get("severity", "").strip()
            source = match.get("source", "")
            
            if diagnosis:
                diagnoses.append(f"log-line = {matched_line}\n{diagnosis}")
            if solution:
                solutions.append(f"log-line = {matched_line}\n{solution}")
            if prevention:
                preventions.append(f"log-line = {matched_line}\n{prevention}")
            if error_type:
                error_types.append(f"log-line = {matched_line}\n{error_type}")
            if severity:
                severities.append(f"log-line = {matched_line}\n{severity}")
            if source:
                sources.add(source)
        
        if diagnoses:
            sections.append("diagnosis:\n" + "\n\n".join(diagnoses))
        if solutions:
            sections.append("solution:\n" + "\n\n".join(solutions))
        if preventions:
            sections.append("prevention:\n" + "\n\n".join(preventions))
        if error_types:
            sections.append("error_type:\n" + "\n\n".join(error_types))
        if severities:
            sections.append("severity:\n" + "\n\n".join(severities))
        if sources:
            sections.append("retrieved_sources:\n" + "\n".join(sorted(sources)))
        
        return "\n\n".join(sections) if sections else ""

    def _extract_basic_error(self, log_text: str) -> tuple[str, str, str | None]:
        traceback_match = re.search(
            r"(Traceback \(most recent call last\):.*?)(?=\n\n|\Z)",
            log_text,
            re.DOTALL,
        )
        if traceback_match:
            traceback = traceback_match.group(1)
            error_match = re.search(r"([A-Za-z_][\w.]*(?:Error|Exception|Warning)):\s*(.+)", traceback)
            if error_match:
                file_match = re.findall(r'File "([^"]+)", line (\d+)', traceback)
                error_line = None
                if file_match:
                    file_path, line_no = file_match[-1]
                    error_line = f"{file_path}:{line_no}"
                return error_match.group(1), error_match.group(2).strip(), error_line

        error_line_match = re.search(r"ERROR\s+-\s+(.+)", log_text)
        if error_line_match:
            return "LogError", error_line_match.group(1).strip(), None

        return "UnknownError", "Unknown failure in task log", None

    def _build_report_without_llm(self, failure: TaskFailure, rag_analysis: dict) -> ErrorReport:
        fallback_type, fallback_message, fallback_line = self._extract_basic_error(failure.log_text)
        matches = rag_analysis.get("matches", [])
        if matches:
            first_match = matches[0]
            diagnosis = first_match.get("diagnosis") or "Unable to use the LLM. Falling back to retrieved evidence from the knowledge base and raw logs."
            error_type = first_match.get("error_type") or fallback_type
            error_message = first_match.get("kb_document") or fallback_message  # or matched_line?
            prevention = first_match.get("prevention", "")
            solution = first_match.get("solution", "")
            sources = [m.get("source") for m in matches if m.get("source")]
        else:
            diagnosis = "Unable to use the LLM. Falling back to retrieved evidence from the knowledge base and raw logs."
            error_type = fallback_type
            error_message = fallback_message
            prevention = ""
            solution = ""
            sources = []
        
        return ErrorReport(
            task_id=failure.task_id,
            error_type=error_type,
            error_message=error_message,
            error_line=fallback_line,
            diagnosis=diagnosis,
            confidence=0.9 if matches else 0.45,
            raw_log=failure.log_text,
            rag_error_location=rag_analysis.get("error_location"),
            rag_diagnosis=diagnosis,
            rag_solution=solution,
            rag_prevention=prevention,
            rag_sources=sources,
        )

    def _strip_json_fence(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()

    def analyse(self, failure: TaskFailure) -> ErrorReport:
        print(f"[LogAnalyser] 🔍 Analysing log for task: {failure.task_id}")

        rag_analysis = self._get_rag_analysis(failure)
        rag_context = self._format_rag_context(rag_analysis)
        rag_section = f"\n\nAdditional context from knowledge base:\n{rag_context}" \
                      if rag_context else ""

        if not self.client:
            report = self._build_report_without_llm(failure, rag_analysis)
            print(f"[LogAnalyser] ✅ Fallback analysis used: {report.error_type} "
                  f"(confidence: {report.confidence})")
            return report

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

        try:
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )

            raw = self._strip_json_fence(response.choices[0].message.content.strip())
            parsed = json.loads(raw)
        except Exception as exc:
            print(f"[LogAnalyser] LLM parse failed, using fallback analysis: {exc}")
            return self._build_report_without_llm(failure, rag_analysis)

        report = ErrorReport(
            task_id      = failure.task_id,
            error_type   = parsed["error_type"],
            error_message= parsed["error_message"],
            error_line   = parsed.get("error_line"),
            diagnosis    = parsed["diagnosis"],
            confidence   = float(parsed["confidence"]),
            raw_log      = failure.log_text,
            rag_error_location = rag_analysis.get("error_location"),
            rag_diagnosis = rag_analysis.get("matches", [{}])[0].get("diagnosis") if rag_analysis.get("matches") else None,
            rag_solution = rag_analysis.get("matches", [{}])[0].get("solution") if rag_analysis.get("matches") else None,
            rag_prevention = rag_analysis.get("matches", [{}])[0].get("prevention") if rag_analysis.get("matches") else None,
            rag_sources = rag_analysis.get("retrieved_sources", []),
        )

        print(f"[LogAnalyser] ✅ Error identified: {report.error_type} "
              f"(confidence: {report.confidence})")
        return report
