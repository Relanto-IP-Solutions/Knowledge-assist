# Synthetic data placeholders

These files exist only so the repository has a working directory layout.

Replace with your own **synthetic** test fixtures before running:

- `scripts/test_ingestion_and_rag.sh`
- any smoke tests that reference `data/test/*`

## Required formats (high level)

1. Zoom: a `.vtt` transcript with at least one valid cue.
2. Slack: exported Slack thread JSON + metadata JSON (matching what `gcs-file-processor` expects after preprocessing).
3. Mock chunks (optional): `sase_mock_chunks.json` if you run agent tests without Vector Search.

