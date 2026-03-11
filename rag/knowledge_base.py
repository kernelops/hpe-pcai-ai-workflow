"""
knowledge_base.py
Builds and manages the ChromaDB knowledge base.
Contains:
- Mock HPE documentation snippets
- Mock past error logs + their fixes
Swap mock data with real PDFs/docs later.
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict

# Collection names
DOCS_COLLECTION = "hpe_docs"
ERRORS_COLLECTION = "past_errors"

# --- Mock HPE Documentation ---
MOCK_HPE_DOCS = [
    {
        "id": "doc_001",
        "text": "HPE iLO Configuration: iLO (Integrated Lights-Out) requires network configuration before OS deployment. "
                "Ensure iLO IP is reachable and credentials are set. Common errors include 'Connection refused' when "
                "iLO port 443 is blocked, and 'Authentication failed' when default credentials haven't been changed. "
                "Fix: Verify network connectivity with ping, check firewall rules for port 443, reset iLO credentials via physical access.",
        "source": "HPE iLO Setup Guide"
    },
    {
        "id": "doc_002",
        "text": "SPP (Service Pack for ProLiant) Deployment: SPP must match the server hardware generation. "
                "Deploying wrong SPP version causes 'Incompatible firmware' errors. "
                "Always verify server model against SPP release notes before deployment. "
                "Fix: Download correct SPP ISO from HPE portal, verify checksum, remount and retry.",
        "source": "HPE SPP Deployment Guide"
    },
    {
        "id": "doc_003",
        "text": "OS Deployment on HPE Servers: OS installation via automated pipeline requires correct boot order. "
                "Errors like 'No bootable device found' occur when PXE boot is not enabled or BIOS boot mode mismatch (UEFI vs Legacy). "
                "Fix: Enter BIOS, enable PXE boot, ensure boot mode matches OS installer (UEFI for modern OS).",
        "source": "HPE OS Deployment Guide"
    },
    {
        "id": "doc_004",
        "text": "MinIO Object Storage Configuration: MinIO requires correct endpoint URL, access key and secret key. "
                "Errors include 'S3 endpoint unreachable', 'Access Denied', and 'Bucket not found'. "
                "Fix: Verify MinIO service is running (systemctl status minio), check access/secret keys in config, "
                "create bucket manually if missing using mc mb command.",
        "source": "MinIO on HPE PCAI Guide"
    },
    {
        "id": "doc_005",
        "text": "Network Configuration on PCAI Rack: Aruba and NVIDIA switches require VLAN configuration for inter-node communication. "
                "Errors include 'Host unreachable' between control and worker nodes, caused by missing VLAN tags. "
                "Fix: SSH into switch, verify VLAN config, add missing VLAN tags to relevant ports.",
        "source": "HPE PCAI Network Guide"
    },
    {
        "id": "doc_006",
        "text": "NFS Configuration: NFS server must be running on control node before worker nodes attempt to mount. "
                "Error 'mount.nfs: Connection timed out' means NFS service is down or firewall is blocking port 2049. "
                "Fix: Run 'systemctl start nfs-server' on control node, open port 2049 in firewall.",
        "source": "HPE PCAI Storage Guide"
    },
    {
        "id": "doc_007",
        "text": "GLFS (GlusterFS) Cluster Setup: GlusterFS peer probe fails when hostname resolution fails between nodes. "
                "Error: 'Probe returned with unknown errno 107'. "
                "Fix: Ensure /etc/hosts has entries for all nodes, verify glusterd service is running on all nodes.",
        "source": "HPE PCAI GLFS Guide"
    },
]

# --- Mock Past Errors & Fixes ---
MOCK_PAST_ERRORS = [
    {
        "id": "err_001",
        "text": "Error: ConnectionRefusedError during iLO configuration task. "
                "Task: configure_ilo | iLO IP 192.168.1.10 port 443 refused connection. "
                "Root Cause: iLO network interface not enabled after factory reset. "
                "Fix Applied: Enabled iLO dedicated network port via physical server access, re-ran configure_ilo task successfully.",
        "source": "Past Error Log #001"
    },
    {
        "id": "err_002",
        "text": "Error: TimeoutError during deploy_os task. "
                "PXE boot timeout after 300 seconds. Server did not receive PXE response. "
                "Root Cause: BIOS boot order had local disk before PXE. "
                "Fix Applied: Changed BIOS boot order to PXE first via iLO virtual console, re-triggered deploy_os.",
        "source": "Past Error Log #002"
    },
    {
        "id": "err_003",
        "text": "Error: S3Error Access Denied during configure_storage task. "
                "MinIO bucket 'pcai-data' access denied with provided credentials. "
                "Root Cause: Access key rotated but pipeline config not updated. "
                "Fix Applied: Updated MINIO_ACCESS_KEY and MINIO_SECRET_KEY in pipeline config, re-ran configure_storage.",
        "source": "Past Error Log #003"
    },
    {
        "id": "err_004",
        "text": "Error: AnsibleConnectionError during configure_network task. "
                "SSH connection to worker node 192.168.2.5 failed. "
                "Root Cause: Worker node OS not yet fully booted when network config task triggered. "
                "Fix Applied: Added wait_for_connection task before configure_network in Airflow DAG.",
        "source": "Past Error Log #004"
    },
    {
        "id": "err_005",
        "text": "Error: CalledProcessError during deploy_spp task. "
                "SPP ISO mount failed: wrong SPP version for Gen10 server. "
                "Root Cause: SPP 2022.09 used but server requires SPP 2023.03 for Gen10 Plus. "
                "Fix Applied: Downloaded SPP 2023.03 ISO, updated SPP_ISO_PATH in config, re-ran deploy_spp.",
        "source": "Past Error Log #005"
    },
    {
        "id": "err_006",
        "text": "Error: NFSMountError on worker node during configure_storage task. "
                "mount.nfs: Connection timed out for 10.0.0.1:/exports/pcai. "
                "Root Cause: nfs-server service not started on control node. "
                "Fix Applied: Ran systemctl enable --now nfs-server on control node, opened port 2049 in firewalld.",
        "source": "Past Error Log #006"
    },
]


def get_embedding_function():
    """Returns sentence-transformers embedding function for ChromaDB."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-mpnet-base-v2"
    )


def build_knowledge_base(persist_dir: str = "./chroma_db") -> chromadb.ClientAPI:
    """
    Initializes ChromaDB, creates collections, and ingests mock data.
    Safe to call multiple times — skips if already populated.
    """
    client = chromadb.PersistentClient(path=persist_dir)
    ef = get_embedding_function()

    # --- HPE Docs Collection ---
    docs_col = client.get_or_create_collection(
        name=DOCS_COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    if docs_col.count() == 0:
        print("[KnowledgeBase] Ingesting HPE documentation...")
        docs_col.add(
            ids=[d["id"] for d in MOCK_HPE_DOCS],
            documents=[d["text"] for d in MOCK_HPE_DOCS],
            metadatas=[{"source": d["source"]} for d in MOCK_HPE_DOCS],
        )
        print(f"[KnowledgeBase] Added {len(MOCK_HPE_DOCS)} HPE doc chunks.")
    else:
        print(f"[KnowledgeBase] HPE docs collection already has {docs_col.count()} entries.")

    # --- Past Errors Collection ---
    errors_col = client.get_or_create_collection(
        name=ERRORS_COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    if errors_col.count() == 0:
        print("[KnowledgeBase] Ingesting past error logs...")
        errors_col.add(
            ids=[e["id"] for e in MOCK_PAST_ERRORS],
            documents=[e["text"] for e in MOCK_PAST_ERRORS],
            metadatas=[{"source": e["source"]} for e in MOCK_PAST_ERRORS],
        )
        print(f"[KnowledgeBase] Added {len(MOCK_PAST_ERRORS)} past error entries.")
    else:
        print(f"[KnowledgeBase] Past errors collection already has {errors_col.count()} entries.")

    return client


def retrieve_context(
    query: str,
    client: chromadb.ClientAPI,
    top_k: int = 3
) -> List[Dict]:
    """
    Retrieves top_k relevant chunks from both collections for the given query.
    Returns combined list of results with source info.
    """
    ef = get_embedding_function()
    results = []

    for collection_name in [DOCS_COLLECTION, ERRORS_COLLECTION]:
        col = client.get_collection(name=collection_name, embedding_function=ef)
        query_results = col.query(
            query_texts=[query],
            n_results=min(top_k, col.count()),
        )
        for doc, meta in zip(query_results["documents"][0], query_results["metadatas"][0]):
            results.append({"text": doc, "source": meta.get("source", "Unknown")})

    return results