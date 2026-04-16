# Multi-connector runbook (Slack + Gmail + Drive)

This runbook explains how **Slack**, **Gmail**, and **Google Drive** connectors work together in this repo, and how Cloud Scheduler should run them.

## Core concept: discovery vs sync

- **Discovery endpoints**: create/update **DB rows** (`opportunities`, `opportunity_sources`) so the system knows *what to sync*.
- **Sync endpoints**: fetch data from connectors and write to **GCS raw/**.

## Endpoints you will use

| Endpoint | What it does | When to call |
|---|---|---|
| `POST /slack/discover` | Lists Slack channels using a connector user token; parses OID from **channel names**; upserts `opportunities` + `opportunity_sources(slack)` | Whenever channels/new OIDs are created in Slack |
| `POST /gmail/discover` | Lists Gmail threads matching `GMAIL_DISCOVER_QUERY`; reads **Subject**; parses OID; upserts `opportunities` + `opportunity_sources(gmail)` | Whenever new OID email threads exist but there is no DB record yet |
| `POST /drive/discover` | Lists Drive folders under `DRIVE_ROOT_FOLDER_NAME` (e.g. `Requirements/`); parses OID from **folder names**; upserts `opportunities` + `opportunity_sources(drive)` | Whenever new opportunity folders are created in Drive |
| `POST /sync/trigger` | Runs sync for **all** rows in `opportunity_sources` (slack/gmail/drive/zoom/…) | Manual one-off sync |
| `POST /sync/run` | **Orchestrates**: Slack discover → Gmail discover → Drive discover → sync | **Cloud Scheduler** (recommended single job) |

## Naming rules (how the system maps data to an opportunity)

### Slack
- Slack sync selects channels whose names **start with** an alphanumeric prefix derived from `opportunities.opportunity_id`.
- Example: `oid1023` → prefix `oid1023` → channels `oid1023-general`, `oid1023-security`.

### Gmail
- Gmail sync searches by **subject**: `subject:"{opportunities.opportunity_id}"`.
- Practical rule: include the opportunity id string in the email subject, e.g. `Re: oid1023 - discovery notes`.
- Gmail discovery scans thread subjects using `GMAIL_DISCOVER_QUERY` and extracts ids (same rules as Slack/Drive).

### Drive
- Drive discovery expects a root folder named `DRIVE_ROOT_FOLDER_NAME` (e.g. `Requirements`) and subfolders whose names contain an opportunity id token (e.g. `oid1023`).
- Drive sync uploads files from the selected folder tree to `{oid}/raw/documents/...`.

## Where data goes in GCS

Per opportunity id `{oid}`:

- **Raw (connector output)**:
  - `{oid}/raw/slack/...`
  - `{oid}/raw/gmail/{thread_id}/thread.json`
  - `{oid}/raw/documents/...`
  - `{oid}/raw/zoom/...` (if enabled)

- **Processed (RAG-ready)** (via `gcs-file-processor` pipeline):
  - `{oid}/processed/slack_messages/...`
  - `{oid}/processed/gmail_messages/{thread_id}/content.txt`
  - `{oid}/processed/documents/...`
  - `{oid}/processed/zoom_transcripts/...`

## Database tables to check

| Table | What it represents |
|---|---|
| `users` | Connector users; Slack token (`slack_access_token`) and Google refresh token (`google_refresh_token`) live here |
| `opportunities` | One row per opportunity id (`oid1234`) |
| `opportunity_sources` | One row per connector per opportunity (`slack`, `gmail`, `drive`, `zoom`) with `last_synced_at` + `sync_checkpoint` |

## Cloud Scheduler (single job)

Your Scheduler should call **only one endpoint**:

- `POST https://<data-connectors-cloud-run-url>/sync/run`
- Schedule: `*/15 * * * *` (or your desired cadence)

This one call keeps DB onboarding up-to-date (Slack/Gmail/Drive discovery) and then runs the full sync.

## Key env vars (Cloud Run)

- **Slack discover**: `SLACK_CONNECTOR_USER_EMAIL` (optional)
- **Gmail discover**: `GMAIL_CONNECTOR_USER_EMAIL` (optional), `GMAIL_DISCOVER_QUERY`, `GMAIL_DISCOVER_MAX_THREADS`
- **Drive discover**: `DRIVE_ROOT_FOLDER_NAME`, `DRIVE_CONNECTOR_USER_EMAIL` (optional), `DRIVE_SUPPORTS_ALL_DRIVES`
- **Google OAuth client** (Drive/Gmail): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- **GCS**: `GCS_BUCKET_INGESTION`

