#!/usr/bin/env python3
"""Run connector smoke + optional ingestion + optional answer-generation smoke; merge JSON.

This script orchestrates (by default):
  1) ``smoke_connectors_discover_and_sync.py`` — data connectors (discover + sync)
  2) Local ``GcsPipeline.run()`` — raw → processed for one OID (optional)
  3) ``smoke_answer_generation`` — LLM pipeline with mock retrievals (optional)

Writes one combined report JSON (``--save-json``).

Examples
--------
  # All three (local API + local ingestion for oid0123 + answer gen)
  uv run python scripts/tests_integration/smoke_e2e_merge.py \\
    --save-json output/e2e_merged.json \\
    --opportunity-id oid0123

  # Connectors only (same as running smoke_connectors_discover_and_sync alone)
  uv run python scripts/tests_integration/smoke_e2e_merge.py \\
    --skip-ingestion --skip-answer-generation --save-json output/e2e_connectors_only.json

  # Skip connectors; only ingestion + answer gen (after you already synced)
  uv run python scripts/tests_integration/smoke_e2e_merge.py \\
    --skip-connectors --opportunity-id oid0123 --save-json output/e2e_rest.json

  # Cloud Run connectors + identity token
  uv run python scripts/tests_integration/smoke_e2e_merge.py \\
    --base-url https://YOUR-SERVICE.run.app --identity-token \\
    --opportunity-id oid0123 --save-json output/e2e_merged.json

Requires
--------
  - Same env as the sub-scripts (see each script’s docstring).
  - Ingestion step needs ``GOOGLE_APPLICATION_CREDENTIALS``, ``GCS_BUCKET_INGESTION``, etc.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    if (_PROJECT_ROOT / "configs" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=False)
    if (_PROJECT_ROOT / "configs" / "secrets" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)
except ImportError:
    pass


def _run_subprocess(
    cmd: list[str], *, cwd: Path, timeout: float | None = 600
) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Merge connector + ingestion + answer-generation smoke into one JSON report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    default_base = (
        os.environ.get("SMOKE_API_BASE_URL")
        or os.environ.get("API_BASE_URL")
        or "http://127.0.0.1:8080"
    ).rstrip("/")
    p.add_argument("--base-url", default=default_base, help="API root for connector smoke")
    p.add_argument("--token", default=os.environ.get("SMOKE_API_TOKEN", ""))
    p.add_argument("--identity-token", action="store_true")
    p.add_argument("--impersonate-service-account", default="")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--zoom-days", type=int, default=14)
    p.add_argument(
        "--sync-run",
        action="store_true",
        help="Use POST /sync/run instead of per-connector + /sync/trigger",
    )
    p.add_argument("--skip-zoom-discover", action="store_true")
    p.add_argument("--no-sync", action="store_true", help="Pass to connector smoke")
    p.add_argument("--validate-oid", default="", metavar="OID")

    p.add_argument(
        "--skip-connectors",
        action="store_true",
        help="Do not run smoke_connectors_discover_and_sync",
    )
    p.add_argument(
        "--skip-ingestion",
        action="store_true",
        help="Do not run GcsPipeline (local raw→processed)",
    )
    p.add_argument(
        "--skip-answer-generation",
        action="store_true",
        help="Do not run smoke_answer_generation",
    )
    p.add_argument(
        "--opportunity-id",
        "-o",
        default="",
        help="OID for local GcsPipeline (e.g. oid0123). Required for ingestion unless skipped.",
    )
    p.add_argument(
        "--save-json",
        metavar="PATH",
        default="",
        help="Write merged report JSON here",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps and exit 0",
    )
    args = p.parse_args()

    py = sys.executable
    connector_script = _PROJECT_ROOT / "scripts" / "tests_integration" / "smoke_connectors_discover_and_sync.py"
    answer_script = "scripts.tests_integration.smoke_answer_generation"

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "connectors": None,
        "ingestion": None,
        "answer_generation": None,
    }

    if args.dry_run:
        print("Dry run — would execute:")
        if not args.skip_connectors:
            print(f"  1) {py} {connector_script} --base-url {args.base_url} ...")
        if not args.skip_ingestion:
            print(
                f"  2) GcsPipeline.run(opportunity_id={args.opportunity_id!r}, since=None)"
            )
        if not args.skip_answer_generation:
            print(f"  3) {py} -m {answer_script}")
        return 0

    failures = 0

    # --- 1) Connectors ---
    if not args.skip_connectors:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix="_connectors.json",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            cmd = [
                py,
                str(connector_script),
                "--base-url",
                args.base_url,
                "--timeout",
                str(args.timeout),
                "--zoom-days",
                str(args.zoom_days),
                "--save-json",
                str(tmp_path),
            ]
            if args.sync_run:
                cmd.append("--sync-run")
            if args.skip_zoom_discover:
                cmd.append("--skip-zoom-discover")
            if args.no_sync:
                cmd.append("--no-sync")
            vo = (args.validate_oid or "").strip()
            if vo:
                cmd.extend(["--validate-oid", vo])
            tok = (args.token or "").strip()
            if tok:
                cmd.extend(["--token", tok])
            if args.identity_token:
                cmd.append("--identity-token")
            imp = (args.impersonate_service_account or "").strip()
            if imp:
                cmd.extend(["--impersonate-service-account", imp])

            code, out, err = _run_subprocess(cmd, cwd=_PROJECT_ROOT, timeout=args.timeout + 60)
            if out:
                print(out, end="")
            if err:
                print(err, end="", file=sys.stderr)
            if code != 0:
                failures += 1
            if tmp_path.exists():
                try:
                    report["connectors"] = _load_json(tmp_path)
                except Exception as e:
                    report["connectors"] = {"error": f"failed to load connector JSON: {e}"}
            else:
                report["connectors"] = {"error": "connector report file missing"}
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    else:
        report["connectors"] = {"skipped": True}

    # --- 2) Ingestion (local GcsPipeline) ---
    if not args.skip_ingestion:
        oid = (args.opportunity_id or "").strip()
        if not oid:
            report["ingestion"] = {
                "skipped": True,
                "reason": "pass --opportunity-id to run GcsPipeline locally",
            }
        else:
            try:
                from src.services.pipelines.gcs_pipeline import GcsPipeline
                from src.utils.opportunity_id import normalize_opportunity_oid

                oid_n = normalize_opportunity_oid(oid)
                gp = GcsPipeline()
                written, deleted = gp.run(opportunity_id=oid_n, since=None)
                report["ingestion"] = {
                    "mode": "local_gcs_pipeline",
                    "opportunity_id": oid_n,
                    "written_count": len(written),
                    "deleted_count": len(deleted),
                    "written_uris_sample": written[:20],
                    "deleted_uris_sample": deleted[:20],
                }
            except Exception as e:
                failures += 1
                report["ingestion"] = {"ok": False, "error": str(e)}
    else:
        report["ingestion"] = {"skipped": True}

    # --- 3) Answer generation (mock retrievals) ---
    if not args.skip_answer_generation:
        cmd = [py, "-m", answer_script]
        code, out, err = _run_subprocess(cmd, cwd=_PROJECT_ROOT, timeout=3600)
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        if code != 0:
            failures += 1
        # List newest file in data/output matching results pattern
        out_dir = _PROJECT_ROOT / "data" / "output"
        latest: str | None = None
        if out_dir.is_dir():
            files = sorted(
                out_dir.glob("*results*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if files:
                latest = str(files[0].resolve())
        report["answer_generation"] = {
            "subprocess_exit_code": code,
            "latest_results_json": latest,
            "note": "Uses mock retrievals from data/context/sase_mock_chunks.json",
        }
    else:
        report["answer_generation"] = {"skipped": True}

    report["failure_count"] = failures
    report["ok"] = failures == 0

    save = (args.save_json or "").strip()
    if save:
        out_path = Path(save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nMerged report written → {out_path.resolve()}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
