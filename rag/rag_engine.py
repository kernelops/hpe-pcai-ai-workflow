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
    from .knowledge_base import (
        get_embedding_function,
        ERRORS_COLLECTION,
        COMMANDS_COLLECTION,
        FIX_STRATEGIES_COLLECTION,
    )
except ImportError:
    from log_parser import ParsedError, format_error_location
    from knowledge_base import (
        get_embedding_function,
        ERRORS_COLLECTION,
        COMMANDS_COLLECTION,
        FIX_STRATEGIES_COLLECTION,
    )


# Cosine similarity is stored as distance in ChromaDB (hnsw:space=cosine).
# ChromaDB returns distances where 0 = identical, 1 = orthogonal, 2 = opposite.
# We convert: similarity = 1 - distance.
# Only keep matches where similarity >= this threshold.
SIMILARITY_THRESHOLD = 0.7
COMMAND_MATCH_THRESHOLD = 0.95


def _distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB cosine distance to similarity score (0-1)."""
    return 1.0 - distance


def retrieve_matches(
    candidate_lines: List[str],
    chroma_client: chromadb.ClientAPI,
    top_k: int = 1,
) -> List[Dict]:
    print(f"[RAGEngine] retrieve_matches -> candidate_lines={candidate_lines}, top_k={top_k}, threshold={SIMILARITY_THRESHOLD}")
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
        print("[RAGEngine] retrieve_matches -> no candidate lines provided")
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
        print(f"[RAGEngine] query results for line '{line}': docs={len(documents)}, metas={len(metadatas)}, distances={len(distances)}")
        print(f"[RAGEngine] query returned documents={documents}")
        print(f"[RAGEngine] query returned distances={distances}")

        for doc, meta, dist in zip(documents, metadatas, distances):
            similarity = _distance_to_similarity(dist)
            print(f"[RAGEngine]   doc='{doc}' dist={dist:.6f} similarity={similarity:.4f}")

            if similarity < SIMILARITY_THRESHOLD:
                print(f"[RAGEngine]   skipping doc='{doc}' because similarity {similarity:.4f} < threshold {SIMILARITY_THRESHOLD}")
                continue

            existing = best_per_document.get(doc)
            if existing is None or similarity > existing["similarity"]:
                print(f"[RAGEngine]   keeping/updating best match for doc='{doc}' similarity={similarity:.4f}")
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

    print(f"[RAGEngine] retrieve_matches -> {len(best_per_document)} final match(es) after deduplication")
    for match in best_per_document.values():
        print(f"[RAGEngine]   final doc='{match['document']}' sim={match['similarity']:.4f} matched_line='{match['matched_line']}'")
    # Sort by similarity descending
    ranked = sorted(best_per_document.values(), key=lambda x: x["similarity"], reverse=True)
    return ranked

def retrieve_command_matches(
    commands: List[str],
    chroma_client: chromadb.ClientAPI,
) -> List[Dict]:
    """
    Retrieves exact command matches from COMMANDS_COLLECTION.
    Only returns matches where similarity == 1.0.
    """
    if not commands:
        return []

    ef = get_embedding_function()

    try:
        col = chroma_client.get_collection(
            name=COMMANDS_COLLECTION,
            embedding_function=ef,
        )
    except Exception as exc:
        print(f"[RAGEngine] Could not access collection '{COMMANDS_COLLECTION}': {exc}")
        return []

    matched_commands = {}

    for command in commands:
        try:
            results = col.query(
                query_texts=[command],
                n_results=1,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            print(f"[RAGEngine] Command query failed for '{command}': {exc}")
            continue

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            similarity = _distance_to_similarity(dist)
            # Only exact matches
            if similarity < COMMAND_MATCH_THRESHOLD:
                continue
            matched_commands[doc] = {
                "command": doc,
                "description": meta.get("description", ""),
                "flags": meta.get("flags", ""),
                "usage": meta.get("usage", ""),
            }

    return list(matched_commands.values())

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
    print(f"[RAGEngine] run_rag_pipeline -> parsed error_type={parsed_error.error_type} error_message={parsed_error.error_message} task_id={parsed_error.task_id}")
    print(f"[RAGEngine] run_rag_pipeline -> candidate_lines={candidate_lines}")

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
        print("[RAGEngine] run_rag_pipeline -> no matches found")
        return {
            "error_location": error_location,
            "error_type": parsed_error.error_type or "Unknown",
            "error_message": parsed_error.error_message,
            "matches": [],
            "retrieved_sources": [],
        }

    print(f"[RAGEngine] run_rag_pipeline -> returning {len(matches)} matches")
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

def run_dag_command_pipeline(
    commands: List[str],
    chroma_client: chromadb.ClientAPI,
) -> Dict:
    """
    DAG command analysis pipeline.
    - Takes extracted commands from dag_parser.py
    - Queries COMMANDS_COLLECTION
    - Returns exact command matches only
    """
    matches = retrieve_command_matches(
        commands=commands,
        chroma_client=chroma_client,
    )
    return {
        "commands_found": commands,
        "matches": matches,
    }


def retrieve_fix_strategies(
    task_id: str,
    error_context: str,
    chroma_client: chromadb.ClientAPI,
    top_k: int = 3,
) -> List[Dict]:
    """
    Query the fix_strategies collection for known remediation patterns.
    Searches using both the task_id and the error context for semantic matching.
    Returns matching fix strategies as structured dicts.
    """
    if not chroma_client:
        return []

    ef = get_embedding_function()

    try:
        col = chroma_client.get_collection(
            name=FIX_STRATEGIES_COLLECTION,
            embedding_function=ef,
        )
    except Exception as exc:
        print(f"[RAGEngine] Could not access collection '{FIX_STRATEGIES_COLLECTION}': {exc}")
        return []

    # Build a query combining task_id and error context for best semantic match
    query_text = f"{task_id}: {error_context}"
    print(f"[RAGEngine] Querying fix strategies for: '{query_text[:100]}'")

    try:
        results = col.query(
            query_texts=[query_text],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        print(f"[RAGEngine] Fix strategy query failed: {exc}")
        return []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    strategies = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        similarity = _distance_to_similarity(dist)
        print(f"[RAGEngine]   fix strategy match: task_id='{meta.get('task_id')}' "
              f"sim={similarity:.4f} desc='{meta.get('description', '')[:60]}'")

        # Use a lower threshold — we want broad matches as context for the LLM
        if similarity < 0.3:
            continue

        strategies.append({
            "task_id": meta.get("task_id", ""),
            "fix_type": meta.get("fix_type", ""),
            "fix_commands": meta.get("fix_commands", "[]"),
            "dry_run_commands": meta.get("dry_run_commands", "[]"),
            "estimated_risk": meta.get("estimated_risk", "medium"),
            "description": meta.get("description", ""),
            "requires_approval": meta.get("requires_approval", "true"),
            "similarity": round(similarity, 4),
            "matched_document": doc,
        })

    print(f"[RAGEngine] Found {len(strategies)} fix strategy match(es)")
    return strategies


def run_fix_strategy_pipeline(
    task_id: str,
    error_context: str,
    chroma_client: chromadb.ClientAPI,
) -> Dict:
    """
    Pipeline entry point for querying fix strategies.
    Returns structured response with matching strategies.
    """
    strategies = retrieve_fix_strategies(
        task_id=task_id,
        error_context=error_context,
        chroma_client=chroma_client,
    )
    return {
        "task_id": task_id,
        "strategies": strategies,
    }