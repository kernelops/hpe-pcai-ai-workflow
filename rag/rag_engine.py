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