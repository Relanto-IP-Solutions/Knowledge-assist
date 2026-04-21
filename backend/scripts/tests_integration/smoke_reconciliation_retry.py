"""Smoke test for orphan reconciliation against GCS vs document_registry (pgvector path).

Uses mocks so no real DB or GCS. Verifies ``_reconcile_orphan_documents`` removes
registry rows via ``delete_document_from_registry`` only (no Vertex Vector Search).

Run with:
  uv run python scripts/tests_integration/smoke_reconciliation_retry.py
  uv run python scripts/tests_integration/smoke_reconciliation_retry.py -v
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


def _make_mock_storage(object_names: list[str] | None = None):
    """GCS list: default empty (all registry docs are orphans); pass object_names for non-empty."""
    storage = MagicMock()
    storage.list_objects.return_value = object_names if object_names is not None else []
    return storage


def _make_mock_registry(
    orphan_doc_id: str,
    datapoint_ids: list[str],
    *,
    doc_row: dict | None = None,
):
    """Registry lists one orphan document; get_chunks reflects datapoint_ids."""
    registry = MagicMock()
    registry.list_document_ids.return_value = [orphan_doc_id]
    registry.get_chunks.return_value = [
        {"datapoint_id": dp_id, "chunk_index": i}
        for i, dp_id in enumerate(datapoint_ids)
    ]
    registry.get_document.return_value = (
        doc_row if doc_row is not None else {"document_id": orphan_doc_id}
    )
    registry.delete_document = MagicMock()
    return registry


def run_smoke_empty_gcs_list(verbose: bool) -> bool:
    """Empty GCS list: every registry doc is an orphan → delete_document once."""
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    print("\n[Test 1] Reconciliation: empty GCS list")
    print(
        "  Setup: list_objects returns []. Registry lists 1 document with 1 chunk. "
        "Expect delete_document once."
    )

    opportunity_id = "OPP-SMOKE-EMPTY-GCS"
    orphan_doc_id = f"{opportunity_id}:documents:only_doc.txt"
    storage = _make_mock_storage()
    registry = _make_mock_registry(orphan_doc_id, ["dp_0"])

    pipeline = IngestionPipeline(storage=storage, registry=registry)
    pipeline._reconcile_orphan_documents(opportunity_id=opportunity_id)

    storage.list_objects.assert_called_with("processed", opportunity_id, "documents")
    if registry.delete_document.call_count != 1:
        print(
            f"  FAIL: expected delete_document once, got {registry.delete_document.call_count}"
        )
        return False
    print("  delete_document: 1. PASS.")
    return True


def run_smoke_two_orphans(verbose: bool) -> bool:
    """Two orphan documents both removed."""
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    print("\n[Test 2] Reconciliation: two orphans")
    opportunity_id = "OPP-SMOKE-TWO"
    id_a = f"{opportunity_id}:documents:a.txt"
    id_b = f"{opportunity_id}:documents:b.txt"
    storage = _make_mock_storage()
    registry = MagicMock()
    registry.list_document_ids.return_value = [id_a, id_b]

    def _chunks(doc_id: str):
        return [{"datapoint_id": f"{doc_id}_dp", "chunk_index": 0}]

    registry.get_chunks.side_effect = _chunks
    registry.get_document.return_value = {"document_id": "x"}
    registry.delete_document = MagicMock()

    pipeline = IngestionPipeline(storage=storage, registry=registry)
    pipeline._reconcile_orphan_documents(opportunity_id=opportunity_id)

    if registry.delete_document.call_count != 2:
        print(
            f"  FAIL: expected delete_document twice, got {registry.delete_document.call_count}"
        )
        return False
    print("  delete_document: 2. PASS.")
    return True


def run_smoke_orphan_doc_row_no_chunks(verbose: bool) -> bool:
    """document_registry row exists but chunk list empty — still delete (cleanup)."""
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    print("\n[Test 3] Reconciliation: document row, zero chunks")
    opportunity_id = "OPP-SMOKE-NO-CHUNKS"
    orphan_doc_id = f"{opportunity_id}:documents:no_chunks_doc.txt"
    storage = _make_mock_storage()
    registry = _make_mock_registry(
        orphan_doc_id, [], doc_row={"document_id": orphan_doc_id}
    )
    registry.get_chunks.return_value = []

    pipeline = IngestionPipeline(storage=storage, registry=registry)
    pipeline._reconcile_orphan_documents(opportunity_id=opportunity_id)

    if registry.delete_document.call_count != 1:
        print(
            f"  FAIL: expected delete_document once, got {registry.delete_document.call_count}"
        )
        return False
    registry.delete_document.assert_called_once_with(orphan_doc_id)
    print("  delete_document: 1 (document row without chunks). PASS.")
    return True


def run_smoke_gcs_matches_registry_no_deletes(verbose: bool) -> bool:
    """GCS lists same object as registry — no orphans, no deletes."""
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    print("\n[Test 4] Reconciliation: GCS matches registry — no deletes")
    opportunity_id = "OPP-SMOKE-MATCH"
    object_name = "still_here.txt"
    doc_id = f"{opportunity_id}:documents:{object_name}"
    storage = _make_mock_storage([object_name])
    registry = _make_mock_registry(doc_id, ["dp_0"])
    registry.list_document_ids.return_value = [doc_id]

    pipeline = IngestionPipeline(storage=storage, registry=registry)
    pipeline._reconcile_orphan_documents(opportunity_id=opportunity_id)

    if registry.delete_document.call_count != 0:
        print(
            f"  FAIL: expected no delete_document calls, got {registry.delete_document.call_count}"
        )
        return False
    print("  delete_document: 0. PASS.")
    return True


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Smoke test reconciliation (pgvector registry only)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable INFO logs from pipeline"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
        )
    else:
        logging.basicConfig(
            level=logging.WARNING, format="%(levelname)s %(name)s %(message)s"
        )
        logging.getLogger("src.services.pipelines.ingestion_pipeline").setLevel(
            logging.CRITICAL
        )

    print("=" * 60)
    print("Smoke test: Reconciliation (registry / pgvector path)")
    print("=" * 60)

    ok1 = run_smoke_empty_gcs_list(args.verbose)
    ok2 = run_smoke_two_orphans(args.verbose)
    ok3 = run_smoke_orphan_doc_row_no_chunks(args.verbose)
    ok4 = run_smoke_gcs_matches_registry_no_deletes(args.verbose)

    print("\n" + "=" * 60)
    if ok1 and ok2 and ok3 and ok4:
        print("All reconciliation smoke tests passed.")
        print("=" * 60)
        return 0
    print("One or more smoke tests failed.")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
