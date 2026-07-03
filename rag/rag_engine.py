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
        FIX_REGISTRY_COLLECTION,
    )
except ImportError:
    from log_parser import ParsedError, format_error_location
    from knowledge_base import (
        get_embedding_function,
        ERRORS_COLLECTION,
        COMMANDS_COLLECTION,
        FIX_REGISTRY_COLLECTION,
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
    print(f"[RAGEngine] Parameters for RAG match:    top_k={top_k}, threshold={SIMILARITY_THRESHOLD}")
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
        #print(f"[RAGEngine] query returned distances={distances}")

        for doc, meta, dist in zip(documents, metadatas, distances):
            similarity = _distance_to_similarity(dist)
            print(f"[RAGEngine]   doc='{doc}' dist={dist:.6f} similarity={similarity:.4f}")

            if similarity < SIMILARITY_THRESHOLD:
                print(f"[RAGEngine]   skipping doc='{doc}' because similarity {similarity:.4f} < threshold {SIMILARITY_THRESHOLD}\n")
                continue

            existing = best_per_document.get(doc)
            if existing is None or similarity > existing["similarity"]:
                print(f"[RAGEngine]   keeping/updating best match for doc='{doc}' similarity={similarity:.4f}\n")
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

    print(f"[RAGEngine] retrieve_matches -> {len(best_per_document)} final match(es) after deduplication\n")
    for match in best_per_document.values():
        print(f"[RAGEngine]   final doc='{match['document']}' sim={match['similarity']:.4f} matched_line='{match['matched_line']}'\n")
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

def retrieve_fix_context(
    task_id: str,
    raw_log: str,
    client: chromadb.ClientAPI,
) -> list[dict]:
    """
    Retrieves fix registry entries for a failed task.

    Strategy:
    1. Embed task_id and query ChromaDB with similarity > 0.95
    2. For each candidate, check if ALL error_line strings appear in the raw_log
    3. Return all entries that pass both checks
    """
    import json

    ef = get_embedding_function()

    try:
        col = client.get_collection(
            name=FIX_REGISTRY_COLLECTION,
            embedding_function=ef
        )
    except Exception as exc:
        print(f"[RAGEngine] Fix registry collection not found: {exc}")
        return []

    try:
        results = col.query(
            query_texts=[task_id],  # ← Keep as task_id
            n_results=min(10, col.count()),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        print(f"[RAGEngine] Fix registry query failed: {exc}")
        return []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    matched_entries = []

    for doc, meta, dist in zip(documents, metadatas, distances):
        similarity = 1.0 - dist

        # Step 1: task_id similarity threshold
        if similarity < 0.95:
            continue

        # Step 2: Check if ALL error_lines are in raw_log
        error_lines = json.loads(meta.get("error_line", "[]"))
        log_lower = raw_log.lower()

        # Check if ALL error_lines are present
        any_line_found = any(
            line.lower() in log_lower
            for line in error_lines
        )

        if not any_line_found:
            print(f"[RAGEngine] No error lines matched for {doc}")
            continue

        print(f"[RAGEngine] Fix registry match — task: {doc}, "
              f"similarity: {similarity:.4f}, "
              f"all error lines found: {error_lines}")

        matched_entries.append({
            "task_id":             doc,
            "similarity":          round(similarity, 4),
            "matched_error_lines": error_lines,  # All lines matched
            "error_line":          error_lines,
            "fix_possibilities":   json.loads(meta.get("fix_possibilities", "[]")),
            "diagnostic_commands": json.loads(meta.get("diagnostic_commands", "[]")),
            "fix_commands":        json.loads(meta.get("fix_commands", "{}")),
        })

    return matched_entries

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
    #print(f"[RAGEngine] run_rag_pipeline -> parsed error_type={parsed_error.error_type} error_message={parsed_error.error_message} task_id={parsed_error.task_id}")
    #print(f"[RAGEngine] run_rag_pipeline -> candidate_lines={candidate_lines}")

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