"""
rag_engine.py
Core RAG logic:
1. Takes a ParsedError
2. Retrieves relevant context from ChromaDB
3. Builds prompt
4. Calls LLaMA3 via Groq API
5. Returns structured solution
"""

import os
from groq import Groq
from typing import List, Dict
try:
    from .log_parser import ParsedError, format_error_location
    from .knowledge_base import retrieve_context
except ImportError:
    from log_parser import ParsedError, format_error_location
    from knowledge_base import retrieve_context
import chromadb


# --- Prompt Template ---
SYSTEM_PROMPT = """You are an expert HPE (Hewlett Packard Enterprise) infrastructure engineer assistant.
You analyze errors from automated build and deployment pipelines for HPE Private Cloud AI (PCAI) systems.
Your job is to:
1. Understand the exact error and where it occurred
2. Use the provided context from HPE documentation and past error fixes
3. Give a clear, actionable solution

Always structure your response EXACTLY as:
DIAGNOSIS: <one sentence explaining what went wrong and why>
SOLUTION:
<numbered step-by-step fix, be specific with commands where applicable>
PREVENTION: <one sentence on how to avoid this in future>"""


def build_prompt(parsed_error: ParsedError, context_chunks: List[Dict]) -> str:
    """Builds the user prompt with error details + retrieved context."""

    error_location = format_error_location(parsed_error)

    context_text = "\n\n".join([
        f"[Source: {chunk['source']}]\n{chunk['text']}"
        for chunk in context_chunks
    ])

    traceback_section = ""
    if parsed_error.raw_traceback:
        traceback_section = f"\nTRACEBACK:\n{parsed_error.raw_traceback}\n"

    prompt = f"""AIRFLOW PIPELINE ERROR REPORT
==============================
ERROR LOCATION: {error_location}
ERROR TYPE: {parsed_error.error_type or 'Unknown'}
ERROR MESSAGE: {parsed_error.error_message}
{traceback_section}
==============================
RELEVANT CONTEXT FROM KNOWLEDGE BASE:
{context_text}
==============================
Based on the error above and the context provided, diagnose the root cause and provide a step-by-step fix."""

    return prompt


def query_llm(prompt: str, groq_api_key: str) -> str:
    """Sends prompt to LLaMA3-8b via Groq and returns response text."""
    if not groq_api_key:
        return ""

    client = Groq(api_key=groq_api_key)

    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        model="llama-3.1-8b-instant",
        temperature=0.2,       # Low temperature = more deterministic/factual
        max_tokens=1024,
    )

    return chat_completion.choices[0].message.content


def _extract_inline_field(text: str, label: str) -> str:
    import re
    match = re.search(rf"{label}:\s*(.*?)(?=(Diagnosis|Solution|Prevention|Causes|$))", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _build_fallback_result(parsed_error: ParsedError, context_chunks: List[Dict]) -> Dict:
    fallback_text = context_chunks[0]["text"] if context_chunks else ""
    diagnosis = _extract_inline_field(fallback_text, "Diagnosis") or (
        f"The task failed with {parsed_error.error_type or 'an unknown error'} and needs manual review."
    )
    solution = _extract_inline_field(fallback_text, "Solution") or (
        "Review the task log, compare it with the closest known error pattern, and retry after applying the fix."
    )
    prevention = _extract_inline_field(fallback_text, "Prevention")
    return {
        "error_location": format_error_location(parsed_error),
        "error_type": parsed_error.error_type or "Unknown",
        "error_message": parsed_error.error_message,
        "diagnosis": diagnosis,
        "solution": solution,
        "prevention": prevention,
        "retrieved_sources": [c["source"] for c in context_chunks],
        "raw_llm_response": "",
    }


def run_rag_pipeline(
    parsed_error: ParsedError,
    chroma_client: chromadb.ClientAPI,
    groq_api_key: str,
    top_k: int = 3,
) -> Dict:
    """
    Full RAG pipeline:
    - Build query from error
    - Retrieve context
    - Build prompt
    - Query LLM
    - Return structured result
    """

    # Build a search query from the error
    search_query = f"{parsed_error.error_type or ''} {parsed_error.error_message} {parsed_error.task_id or ''}"

    # Retrieve relevant context
    context_chunks = retrieve_context(
        query=search_query,
        client=chroma_client,
        top_k=top_k,
    )

    # Build prompt
    prompt = build_prompt(parsed_error, context_chunks)

    # Query LLM
    llm_response = query_llm(prompt, groq_api_key)
    if not llm_response:
        return _build_fallback_result(parsed_error, context_chunks)

    # Parse LLM response sections
    diagnosis = _extract_section(llm_response, "DIAGNOSIS")
    solution = _extract_section(llm_response, "SOLUTION")
    prevention = _extract_section(llm_response, "PREVENTION")

    return {
        "error_location": format_error_location(parsed_error),
        "error_type": parsed_error.error_type or "Unknown",
        "error_message": parsed_error.error_message,
        "diagnosis": diagnosis or llm_response,
        "solution": solution or llm_response,
        "prevention": prevention or "",
        "retrieved_sources": [c["source"] for c in context_chunks],
        "raw_llm_response": llm_response,
    }


def _extract_section(text: str, section_name: str) -> str:
    """Extracts a section from the structured LLM response."""
    import re
    pattern = rf"{section_name}:\s*(.*?)(?=\n[A-Z]+:|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
