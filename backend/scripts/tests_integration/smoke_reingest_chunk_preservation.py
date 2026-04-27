"""Smoke test for re-ingestion chunk preservation (pgvector path).

Verifies the fix for the bug where re-ingesting a document with only the last
paragraph(s) modified caused all earlier chunks' ``chunk_text`` and ``embedding``
to be wiped out.

Two tests, both fully mocked (no real DB, GCS, or Vertex):

  Test 1 — RegistryClient.write_registry:
    Confirms write_registry()
      - does NOT issue a blanket DELETE FROM chunk_registry,
      - skips chunks whose chunk_text is None (preserved as-is in DB),
      - upserts only chunks that carry chunk_text/embedding,
      - issues a targeted tail-delete for chunk_index >= total_chunks,
      - commits exactly once.

  Test 2 — IngestionPipeline.run_message:
    Reproduces the user's scenario: 21-chunk document, only chunks 19/20
    modified on re-ingest. Verifies
      - embed_texts is called exactly once with the 2 modified texts (not 21),
      - write_registry receives a chunks list where indices 0-18 have
        chunk_text=None / no embedding (preserve), and only indices 19/20
        carry the new chunk_text + embedding.

Run with:
  uv run python scripts/tests_integration/smoke_reingest_chunk_preservation.py
  uv run python scripts/tests_integration/smoke_reingest_chunk_preservation.py -v
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


EMBED_DIM = 8


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_sql(sql: str) -> str:
    """Collapse whitespace so we can pattern-match against multi-line SQL."""
    return " ".join(sql.split()).strip()


def _capture_executes(cur_mock: MagicMock) -> list[tuple[str, tuple]]:
    """Return list of (normalized_sql, params) calls made on cur.execute()."""
    calls = []
    for call in cur_mock.execute.call_args_list:
        args = call.args
        sql = args[0] if args else ""
        params = args[1] if len(args) > 1 else ()
        calls.append((_normalize_sql(sql), params))
    return calls


def _build_mock_db_cursor() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (con_mock, cur_mock, get_conn_mock) suitable for patching get_db_connection."""
    cur = MagicMock()
    cur.rowcount = 0
    con = MagicMock()
    con.cursor.return_value = cur
    get_conn = MagicMock(return_value=con)
    return con, cur, get_conn


def run_test_write_registry_preserves(verbose: bool) -> bool:
    """Test 1 — write_registry skips unchanged chunks and tail-deletes only stale rows."""
    from src.services.database_manager import registry as registry_module

    print("\n[Test 1] write_registry: preserve unchanged chunks, tail-delete stale")
    print(
        "  Setup: 5-chunk doc, indices 0-2 unchanged (chunk_text=None), "
        "indices 3-4 changed (chunk_text + embedding provided). total_chunks=5."
    )

    document_id = "oid_smoke:documents:doc.txt"
    opportunity_id = "oid_smoke"
    chunks = [
        {
            "chunk_id": f"src_{i}",
            "chunk_index": i,
            "chunk_hash": f"hash_{i}",
            "datapoint_id": f"dp_{i}",
        }
        for i in range(3)
    ] + [
        {
            "chunk_id": f"src_{i}",
            "chunk_index": i,
            "chunk_hash": f"hash_{i}_new",
            "datapoint_id": f"dp_{i}",
            "chunk_text": f"new text {i}",
            "embedding": [0.1] * EMBED_DIM,
        }
        for i in range(3, 5)
    ]

    con, cur, get_conn = _build_mock_db_cursor()

    with patch.object(registry_module, "get_db_connection", get_conn):
        client = registry_module.RegistryClient()
        client.write_registry(
            document_id=document_id,
            opportunity_id=opportunity_id,
            gcs_path="oid_smoke/processed/documents/doc.txt",
            doc_hash="dochash",
            total_chunks=5,
            chunks=chunks,
            source_type="documents",
        )

    calls = _capture_executes(cur)
    if verbose:
        for i, (sql, params) in enumerate(calls):
            print(f"    [{i}] {sql[:120]}{'...' if len(sql) > 120 else ''}")

    insert_doc = [c for c in calls if c[0].startswith("INSERT INTO document_registry")]
    insert_chunk = [c for c in calls if c[0].startswith("INSERT INTO chunk_registry")]
    delete_blanket = [
        c
        for c in calls
        if c[0] == "DELETE FROM chunk_registry WHERE document_id = %s"
    ]
    delete_tail = [
        c
        for c in calls
        if c[0]
        == "DELETE FROM chunk_registry WHERE document_id = %s AND chunk_index >= %s"
    ]

    if len(insert_doc) != 1:
        print(f"  FAIL: expected 1 document_registry upsert, got {len(insert_doc)}")
        return False
    if len(insert_chunk) != 2:
        print(
            f"  FAIL: expected 2 chunk_registry inserts (only indices 3-4), got {len(insert_chunk)}"
        )
        return False
    if delete_blanket:
        print(
            "  FAIL: blanket 'DELETE FROM chunk_registry WHERE document_id = %s' "
            "is back — unchanged chunks would be wiped."
        )
        return False
    if len(delete_tail) != 1:
        print(
            f"  FAIL: expected 1 targeted tail delete, got {len(delete_tail)}"
        )
        return False

    tail_params = delete_tail[0][1]
    if tail_params != (document_id, 5):
        print(
            f"  FAIL: tail delete params {tail_params!r} != ({document_id!r}, 5)"
        )
        return False

    # Verify the chunk_text values inserted are exactly 'new text 3' / 'new text 4'.
    inserted_indices = sorted(c[1][3] for c in insert_chunk)  # chunk_index is 4th param
    inserted_texts = sorted(c[1][8] for c in insert_chunk)  # chunk_text is 9th param
    if inserted_indices != [3, 4]:
        print(f"  FAIL: inserted indices {inserted_indices} != [3, 4]")
        return False
    if inserted_texts != ["new text 3", "new text 4"]:
        print(f"  FAIL: inserted texts {inserted_texts!r}")
        return False

    if con.commit.call_count != 1:
        print(f"  FAIL: expected commit once, got {con.commit.call_count}")
        return False

    print(
        "  inserts=2 (indices 3-4), tail-delete=1 (chunk_index>=5), "
        "blanket-delete=0, commit=1. PASS."
    )
    return True


def run_test_reingest_only_changed_embedded(verbose: bool) -> bool:
    """Test 2 — re-ingest with last 2 chunks modified embeds only those 2."""
    from src.services.pipelines import ingestion_pipeline as ip_module
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    print(
        "\n[Test 2] run_message: 21-chunk doc, only chunks 19/20 modified — "
        "embed_texts called once with 2 texts; write_registry preserves 0-18."
    )

    opportunity_id = "oid_smoke_reingest"
    object_name = "Lexive_Sales_Reference_Guide.txt"
    source_type = "documents"
    bucket = "smoke-bucket"
    data_path = (
        f"gs://{bucket}/{opportunity_id}/processed/{source_type}/{object_name}"
    )
    document_id = f"{opportunity_id}:{source_type}:{object_name}"

    new_chunk_texts = [f"chunk_body_idx_{i}" for i in range(21)]
    new_chunk_texts[19] = "chunk_body_idx_19_MODIFIED"
    new_chunk_texts[20] = "chunk_body_idx_20_MODIFIED"

    new_hashes = [_sha256_hex(t) for t in new_chunk_texts]

    existing_chunks = [
        {
            "chunk_index": i,
            "chunk_hash": new_hashes[i],
            "datapoint_id": f"oid_smoke_reingest__documents__Lexive__{i}",
        }
        for i in range(19)
    ] + [
        {
            "chunk_index": 19,
            "chunk_hash": "OLD_HASH_19",
            "datapoint_id": "oid_smoke_reingest__documents__Lexive__19",
        },
        {
            "chunk_index": 20,
            "chunk_hash": "OLD_HASH_20",
            "datapoint_id": "oid_smoke_reingest__documents__Lexive__20",
        },
    ]

    storage = MagicMock()
    storage.read.return_value = b"raw document bytes (extraction is mocked out)"

    registry = MagicMock()
    registry.get_document.return_value = {"doc_hash": "PREVIOUS_DOC_HASH"}
    registry.get_chunks.return_value = existing_chunks

    pipeline = IngestionPipeline(storage=storage, registry=registry)

    pipeline._documents_chunker = MagicMock()
    pipeline._documents_chunker.extract_and_chunk.return_value = new_chunk_texts

    embed_calls: list[list[str]] = []

    def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        embed_calls.append(list(texts))
        return [[float(i)] * EMBED_DIM for i, _ in enumerate(texts)]

    with (
        patch.object(ip_module, "embed_texts", side_effect=fake_embed_texts),
        patch.object(ip_module, "refresh_opportunity_pipeline_state", lambda *a, **k: None),
        patch.object(ip_module, "Publisher") as publisher_cls,
    ):
        publisher_cls.return_value = MagicMock()
        result = pipeline.run_message({
            "source_type": source_type,
            "data_path": data_path,
            "metadata": {
                "opportunity_id": opportunity_id,
                "channel": "gdrive",
                "source_id": object_name,
                "document_id": document_id,
            },
        })

    if not result or not result.startswith("documents:"):
        print(f"  FAIL: unexpected run_message result: {result!r}")
        return False

    if len(embed_calls) != 1:
        print(
            f"  FAIL: expected embed_texts to be called once, got {len(embed_calls)} "
            f"(call sizes={[len(c) for c in embed_calls]})"
        )
        return False
    embedded_texts = embed_calls[0]
    if len(embedded_texts) != 2:
        print(
            f"  FAIL: expected 2 texts to embed (chunks 19,20), got {len(embedded_texts)}"
        )
        return False
    if sorted(embedded_texts) != sorted([
        "chunk_body_idx_19_MODIFIED",
        "chunk_body_idx_20_MODIFIED",
    ]):
        print(f"  FAIL: embedded texts mismatch: {embedded_texts!r}")
        return False

    if registry.write_registry.call_count != 1:
        print(
            f"  FAIL: expected write_registry called once, "
            f"got {registry.write_registry.call_count}"
        )
        return False
    kwargs = registry.write_registry.call_args.kwargs
    if kwargs.get("total_chunks") != 21:
        print(f"  FAIL: total_chunks={kwargs.get('total_chunks')!r} (expected 21)")
        return False
    chunks_arg = kwargs.get("chunks") or []
    if len(chunks_arg) != 21:
        print(f"  FAIL: write_registry chunks len={len(chunks_arg)} (expected 21)")
        return False

    indexed = {c["chunk_index"]: c for c in chunks_arg}
    bad_unchanged = [
        i
        for i in range(19)
        if "chunk_text" in indexed[i] or "embedding" in indexed[i]
    ]
    if bad_unchanged:
        print(
            "  FAIL: unchanged chunks carried chunk_text/embedding "
            f"(would overwrite preserved rows): indices={bad_unchanged}"
        )
        return False

    for i in (19, 20):
        c = indexed[i]
        if not c.get("chunk_text"):
            print(f"  FAIL: changed chunk index={i} missing chunk_text")
            return False
        if not c.get("embedding"):
            print(f"  FAIL: changed chunk index={i} missing embedding")
            return False
    if indexed[19]["chunk_text"] != "chunk_body_idx_19_MODIFIED":
        print(f"  FAIL: chunk 19 text = {indexed[19]['chunk_text']!r}")
        return False
    if indexed[20]["chunk_text"] != "chunk_body_idx_20_MODIFIED":
        print(f"  FAIL: chunk 20 text = {indexed[20]['chunk_text']!r}")
        return False

    print(
        "  embed_texts calls: 1 (2 texts). write_registry: total_chunks=21, "
        "indices 0-18 carry NO chunk_text/embedding (preserved), 19/20 carry "
        "new chunk_text + embedding. PASS."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test: re-ingestion chunk preservation"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print captured SQL calls"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
        )
    else:
        logging.basicConfig(level=logging.WARNING)
        logging.getLogger("src.services.pipelines.ingestion_pipeline").setLevel(
            logging.CRITICAL
        )
        logging.getLogger("src.services.database_manager.registry").setLevel(
            logging.CRITICAL
        )

    print("=" * 60)
    print("Smoke test: Re-ingestion chunk preservation (pgvector)")
    print("=" * 60)

    ok1 = run_test_write_registry_preserves(args.verbose)
    ok2 = run_test_reingest_only_changed_embedded(args.verbose)

    print("\n" + "=" * 60)
    if ok1 and ok2:
        print("All re-ingestion smoke tests passed.")
        print("=" * 60)
        return 0
    print("One or more re-ingestion smoke tests failed.")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
