# Drive discovery + full sync orchestration

This runbook describes the **end-to-end flow**: Slack / Gmail / Drive discovery, plugin sync (Slack, Gmail, Drive, Zoom, etc.), scheduled execution on Google Cloud, where state lives in the database, and what happens when folders or files change.

## What the API does

| Endpoint | Purpose |
|----------|---------|
| `POST /slack/discover` | Lists Slack channels (bot token), parses opportunity ids from **channel names** (canonical: `oid1234`), **upserts** `opportunities` and **one** `opportunity_sources` row with `source_type='slack'` per opportunity (same naming rules as manual `POST /opportunities/slack`). Optional: `SLACK_CONNECTOR_USER_EMAIL` to pin which user’s token is used. |
| `POST /gmail/discover` | Lists Gmail threads matching `GMAIL_DISCOVER_QUERY`, reads each thread’s **Subject**, parses opportunity ids (same rules as Slack/Drive), **upserts** `opportunities` and **one** `opportunity_sources` row with `source_type='gmail'` per opportunity. Uses `google_refresh_token` (optional `GMAIL_CONNECTOR_USER_EMAIL` or `DRIVE_CONNECTOR_USER_EMAIL`). Tune `GMAIL_DISCOVER_MAX_THREADS` if needed. |
| `POST /drive/discover` | Lists direct child folders under `DRIVE_ROOT_FOLDER_NAME` (e.g. `Requirements/`), parses opportunity ids from folder names, **upserts** `opportunities` and **one** `opportunity_sources` row with `source_type='drive'` per opportunity. |
| `POST /sync/trigger` | Runs sync for **every** row in `opportunity_sources` (all connector types). |
| `POST /sync/run` | **Orchestrates**: **Slack discover → Gmail discover → Drive discover → sync**. Intended for Cloud Scheduler so one HTTP call does everything in a deterministic order. |

Nothing in the application code “forces” a 15-minute interval. **How often it runs** is entirely defined by **Cloud Scheduler** (or your own cron) when you create the job.

## Does it run every 15 minutes?

**Only if you configure Cloud Scheduler that way.**

- Example schedule for every 15 minutes: `*/15 * * * *` (cron format).
- If you set the schedule to hourly, daily, or `*/5 * * * *` (every 5 minutes), it will run at that cadence instead.
- Local development: nothing runs on a timer unless you use Task Scheduler, cron, or manually call `POST /sync/run`.

So: **15 minutes is a recommended default for Drive freshness**, not a built-in constant in the app.

## New files in an existing opportunity folder

**Yes.** On each sync, the Drive plugin:

- Walks the **selected** opportunity folder tree recursively.
- For each file, compares Google Drive `file_id` and `modifiedTime` against the JSON stored in `opportunity_sources.sync_checkpoint`.
- **New files** (new `file_id`) are uploaded to GCS.
- **Changed files** (same `file_id`, different `modifiedTime`) are uploaded again and the checkpoint is updated **only after a successful GCS write**.

So adding a PDF or Excel under the same OID folder and running `POST /sync/trigger` or `POST /sync/run` will pick up those files on the next run (subject to the scheduler or manual trigger).

## Where to see “entries” (database vs GCS)

### PostgreSQL tables (operational / sync state)

| Table | What you see |
|-------|----------------|
| `users` | Connector user(s); `google_refresh_token` must be set for Drive sync. Optional: align with `DRIVE_CONNECTOR_USER_EMAIL`. |
| `opportunities` | One row per opportunity id (e.g. `oid1023`). `opportunity_id` is unique. |
| `opportunity_sources` | One row per **source type** per opportunity (e.g. one `slack`, one `drive`, one `gmail`). Columns **`last_synced_at`** and **`sync_checkpoint`** (JSON: Drive file IDs → last modified time) drive incremental behavior for Drive. |

Useful example queries:

```sql
-- Opportunities and their connector sources
SELECT o.opportunity_id, o.name, s.source_type, s.id AS source_id, s.last_synced_at
FROM opportunities o
LEFT JOIN opportunity_sources s ON s.opportunity_id = o.id
ORDER BY o.opportunity_id, s.source_type;

-- Drive checkpoint size / freshness (rough)
SELECT o.opportunity_id, s.last_synced_at,
       LENGTH(COALESCE(s.sync_checkpoint, '')) AS checkpoint_chars
FROM opportunity_sources s
JOIN opportunities o ON o.id = s.opportunity_id
WHERE s.source_type = 'drive';
```

### Google Cloud Storage (raw documents)

Uploaded Drive files land under your ingestion bucket, typically:

`{oid}/raw/documents/...`

That is the **file** layer the ingestion/RAG pipeline consumes, not a separate “table.”

### After ingestion / embedding (RAG)

If your deployment runs chunking and embedding into pgvector, document chunks may appear in tables such as **`chunk_registry`** (and related tables your pipeline defines). That is **downstream** of raw GCS sync; it is not updated by `POST /sync/run` alone unless you also run the ingestion pipeline.

## Two folders under `Requirements/` with the same opportunity ID

Example: `Requirements/oid1023-general/` and `Requirements/oid1023-security/`.

### Discovery (`POST /drive/discover` or the discover step inside `POST /sync/run`)

- Folder names are parsed with an opportunity id token; both folders map to the **same** `opportunities.opportunity_id` (e.g. `oid1023`).
- The app maintains **at most one** `opportunity_sources` row with `source_type='drive'` per opportunity. A second folder with the same OID **does not** create a second Drive source row.

### Sync (`drive_plugin`)

- Under `DRIVE_ROOT_FOLDER_NAME`, the plugin searches for subfolders whose **name contains** the opportunity OID, then uses **`found_folders[0]`** — the **first** folder returned by the Drive API.
- **The other folder is not synced** by the current implementation. Order is whatever the API returns (not guaranteed stable).

**Practical guidance**

- Prefer **one folder per id** under `Requirements/` (e.g. `oid1023/` or `oid1023-general/` only).
- If you need multiple roots for the same deal, either **merge content into one folder** or **use distinct OIDs** in folder names so they become separate opportunities (only if that matches your business model).

## Cloud Scheduler: single job calling `POST /sync/run`

1. Deploy the API to Cloud Run (your image, env vars, DB, secrets).
2. Create a service account for Scheduler; grant it **`roles/run.invoker`** on the Cloud Run service.
3. Create an HTTP Cloud Scheduler job:
   - URL: `https://<YOUR_CLOUD_RUN_URL>/sync/run`
   - Method: `POST`
   - Auth: OIDC token with that service account
   - Schedule: e.g. `*/15 * * * *` for every 15 minutes

That one job runs **Drive discovery** and then **full plugin sync** (Slack, Gmail, Drive, Zoom, etc.) in one request.

## Quick reference: manual testing (local)

```bash
# Orchestrated (discover + all sources)
curl -s -X POST http://127.0.0.1:8080/sync/run
```

Inspect the JSON: `drive_discover` summarizes folder upserts; `sync` lists per-`opportunity_id` / `source_type` counts.

## Related docs

- `docs/google-drive-operational-checklist.md` — OAuth, shared drive, env vars, troubleshooting.
- `docs/slack-running-workflow.md` — Slack-specific setup and APIs.
