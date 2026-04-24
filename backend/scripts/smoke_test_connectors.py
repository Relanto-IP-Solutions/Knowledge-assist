from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

# Ensure `src` imports resolve when running:
#   python scripts/smoke_test_connectors.py
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.services.database_manager.connection import get_db_connection
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.services.rag_engine.retrieval.vector_search import (
    retrieve_topk_from_combined_source,
)
from src.services.storage.service import Storage


OID = "oid10020"
DRIVE_EMAIL = "ishitasharma1129@gmail.com"
ONEDRIVE_EMAIL = "ishita.sharma@relanto.ai"
BASE_URL = "http://localhost:8000"
SYNC_WAIT_SECONDS = 15


def _print_result(step_name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {step_name}{suffix}")


def step1_connection_and_sync() -> tuple[bool, str]:
    drive_url = (
        f"{BASE_URL}/integrations/drive/connect/{OID}"
        f"?user_email={DRIVE_EMAIL}"
    )
    onedrive_url = (
        f"{BASE_URL}/integrations/onedrive/connect/{OID}"
        f"?user_email={ONEDRIVE_EMAIL}"
    )

    try:
        drive_resp = requests.post(drive_url, json={}, timeout=120)
    except requests.RequestException as exc:
        return False, f"Drive connect request failed: {exc}"

    if drive_resp.status_code >= 400:
        return (
            False,
            f"Drive connect HTTP {drive_resp.status_code}: {drive_resp.text[:400]}",
        )

    try:
        onedrive_resp = requests.post(onedrive_url, json={}, timeout=120)
    except requests.RequestException as exc:
        return False, f"OneDrive connect request failed: {exc}"

    if onedrive_resp.status_code >= 400:
        return (
            False,
            f"OneDrive connect HTTP {onedrive_resp.status_code}: {onedrive_resp.text[:400]}",
        )

    time.sleep(SYNC_WAIT_SECONDS)
    return True, "Drive + OneDrive connect succeeded; waited for ingestion."


def step2_storage_verification() -> tuple[bool, str]:
    storage = Storage()
    docs = storage.list_objects("raw", OID, "documents")
    onedrive = storage.list_objects("raw", OID, "onedrive")

    docs_count = len(docs)
    onedrive_count = len(onedrive)
    ok = docs_count > 0 and onedrive_count > 0
    detail = f"raw/documents={docs_count}, raw/onedrive={onedrive_count}"
    return ok, detail


def step3_registry_check() -> tuple[bool, str]:
    con = get_db_connection()
    try:
        cur = con.cursor()
        cur.execute(
            """
            SELECT source_type, COUNT(*)
            FROM document_registry
            WHERE opportunity_id = %s
              AND source_type IN ('documents', 'onedrive')
            GROUP BY source_type
            """,
            (OID,),
        )
        rows = cur.fetchall()
    finally:
        con.close()

    counts = {str(st): int(cnt) for st, cnt in rows}
    has_documents = counts.get("documents", 0) > 0
    has_onedrive = counts.get("onedrive", 0) > 0
    ok = has_documents and has_onedrive
    detail = f"document_registry counts={counts}"
    return ok, detail


def step4_retrieval_labels() -> tuple[bool, str]:
    query = os.environ.get(
        "SMOKE_TEST_QUERY",
        "Summarize key project documents for this opportunity.",
    )
    try:
        embedding = embed_texts([query])[0]
    except Exception as exc:
        return False, f"Embedding generation failed: {exc}"

    try:
        results = retrieve_topk_from_combined_source(
            query_embedding=embedding,
            opportunity_id=OID,
            token="",
            top_k=20,
        )
    except Exception as exc:
        return False, f"Retrieval failed: {exc}"

    labels = {str(item.get("source_type") or "").strip() for item in results}
    has_gdrive = "gdrive_doc" in labels
    has_onedrive = "onedrive_doc" in labels
    ok = has_gdrive and has_onedrive
    detail = f"labels={sorted(labels)}"
    return ok, detail


def main() -> int:
    checks = [
        ("Step 1: Connection & Sync", step1_connection_and_sync),
        ("Step 2: Storage Verification", step2_storage_verification),
        ("Step 3: Database Registry Check", step3_registry_check),
        ("Step 4: RAG Retrieval Labels", step4_retrieval_labels),
    ]

    all_ok = True
    for label, fn in checks:
        ok, detail = fn()
        _print_result(label, ok, detail)
        all_ok = all_ok and ok

    if all_ok:
        print("[PASS] Overall smoke test passed.")
        return 0
    print("[FAIL] Overall smoke test failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

