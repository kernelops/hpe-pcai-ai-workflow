"""
rag_engine.py
RAG pipeline — no LLM involved.

Flow:
1. Takes a ParsedError (which now contains candidate_lines)
2. Embeds each candidate line individually
3. Queries ChromaDB for each line
4. Filters matches below similarity threshold
5. Deduplicates (one KB entry per matched document)
6. Extracts diagnosis/solution/prevention from ChromaDB metadata
7. Returns structured result
"""

import chromadb
from typing import List, Dict, Optional

try:
    from .log_parser import ParsedError, format_error_location
    from .knowledge_base import get_embedding_function, ERRORS_COLLECTION
except ImportError:
    from log_parser import ParsedError, format_error_location
    from knowledge_base import get_embedding_function, ERRORS_COLLECTION


# Cosine similarity is stored as distance in ChromaDB (hnsw:space=cosine).
# ChromaDB returns distances where 0 = identical, 1 = orthogonal, 2 = opposite.
# We convert: similarity = 1 - distance.
# Only keep matches where similarity >= this threshold.
SIMILARITY_THRESHOLD = 0.7


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB cosine distance to similarity score (0-1)."""
    return 1.0 - distance


def retrieve_matches(
    candidate_lines: List[str],
    chroma_client: chromadb.ClientAPI,
    top_k: int = 1,
) -> List[Dict]:
    """
    For each candidate line:
      - Query ChromaDB for the closest KB entry
      - Filter out matches below SIMILARITY_THRESHOLD
      - Deduplicate: if multiple lines match the same KB document, keep the highest scoring one

    Returns a list of dicts, each containing:
      {
        "matched_line": str,        # the log line that triggered this match
        "similarity": float,        # similarity score
        "document": str,            # the KB error_line text
        "error_type": str,
        "diagnosis": str,
        "solution": str,
        "prevention": str,
        "severity": str,
        "source": str,
        "retrieved_sources": str,
      }
    """
    if not candidate_lines:
        return []

    ef = get_embedding_function()

    try:
        col = chroma_client.get_collection(name=ERRORS_COLLECTION, embedding_function=ef)
    except Exception as exc:
        print(f"[RAGEngine] Could not access collection '{ERRORS_COLLECTION}': {exc}")
        return []

    # key: document text → best match dict so far (for deduplication)
    best_per_document: Dict[str, Dict] = {}

    for line in candidate_lines:
        try:
            results = col.query(
                query_texts=[line],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            print(f"[RAGEngine] Query failed for line '{line[:60]}': {exc}")
            continue

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            similarity = _distance_to_similarity(dist)

            if similarity < SIMILARITY_THRESHOLD:
                continue

            existing = best_per_document.get(doc)
            if existing is None or similarity > existing["similarity"]:
                best_per_document[doc] = {
                    "matched_line": line,
                    "similarity": similarity,
                    "document": doc,
                    "error_type": meta.get("error_type", "Unknown"),
                    "diagnosis": meta.get("diagnosis", ""),
                    "solution": meta.get("solution", ""),
                    "prevention": meta.get("prevention", ""),
                    "severity": meta.get("severity", ""),
                    "source": meta.get("source", "Unknown"),
                    "retrieved_sources": meta.get("retrieved_sources", ""),
                }

    # Sort by similarity descending
    ranked = sorted(best_per_document.values(), key=lambda x: x["similarity"], reverse=True)
    return ranked


def run_rag_pipeline(
    parsed_error: ParsedError,
    chroma_client: chromadb.ClientAPI,
    top_k: int = 1,
) -> Dict:
    """
    Full RAG pipeline (no LLM).

    - Uses parsed_error.candidate_lines for line-level retrieval
    - Falls back to error_type + error_message if no candidate lines exist
    - Returns all matched KB entries after threshold filtering and deduplication
    """

    candidate_lines = parsed_error.candidate_lines

    # Fallback: if log parser found no candidate lines, build one from the parsed error
    if not candidate_lines:
        fallback_line = " ".join(filter(None, [
            parsed_error.error_type,
            parsed_error.error_message,
            parsed_error.task_id,
        ]))
        if fallback_line.strip():
            candidate_lines = [fallback_line]

    matches = retrieve_matches(
        candidate_lines=candidate_lines,
        chroma_client=chroma_client,
        top_k=top_k,
    )

    error_location = format_error_location(parsed_error)

    if not matches:
        return {
            "error_location": error_location,
            "error_type": parsed_error.error_type or "Unknown",
            "error_message": parsed_error.error_message,
            "matches": [],
            "retrieved_sources": [],
        }

    return {
        "error_location": error_location,
        "error_type": parsed_error.error_type or "Unknown",
        "error_message": parsed_error.error_message,
        "matches": [
            {
                "matched_line": m["matched_line"],
                "similarity": round(m["similarity"], 4),
                "kb_document": m["document"],
                "diagnosis": m["diagnosis"],
                "solution": m["solution"],
                "prevention": m["prevention"],
                "error_type": m["error_type"],
                "severity": m["severity"],
                "source": m["source"],
                "retrieved_sources": m["retrieved_sources"],
            }
            for m in matches
        ],
        "retrieved_sources": list({m["source"] for m in matches}),
    }
