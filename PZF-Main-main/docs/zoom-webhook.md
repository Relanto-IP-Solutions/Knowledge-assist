# Zoom webhook integration runbook

This runbook explains how the **Zoom transcription connector** works in this repo and how to set it up locally and in Cloud Run.

It is based on the internal setup notes (`zoom-integration-setup.md`) and aligned to the merged code on branch `feature/multi-plugin-connectors`.

---

## Architecture (high level)

- **Zoom S2S OAuth app**: backend uses Server-to-Server OAuth to call Zoom APIs.
- **Zoom webhooks**: Zoom sends `recording.completed` / `recording.transcript_completed` to your endpoint.
- **API endpoint**: `POST /integrations/zoom/webhook` receives the webhook, responds quickly, and processes downloads in background.
- **Discovery endpoint**: `POST /zoom/discover` lists recent recordings, extracts `oid###` from meeting topics, and upserts `opportunities` + `opportunity_sources(source_type='zoom')` so `/sync/trigger` can later sync Zoom incrementally.
- **GCS raw tier**: transcript files are written into the ingestion bucket under an opportunity-derived prefix.

---

## 1) Zoom App prerequisites (Marketplace)

Create a **Server-to-Server OAuth** app in the Zoom App Marketplace.

### Required scopes

Your Zoom app needs scopes that allow listing recording files and downloading transcripts:

- `cloud_recording:read:list_recording_files`
- `cloud_recording:read:list_recording_files:admin`

**Token caching note:** if you add scopes later, existing tokens can remain cached for ~60 minutes. Revoke token (or wait) after scope changes.

### Event subscriptions

In the Zoom app Feature / Event Subscriptions:

- **Event**: `recording.completed` (and optionally `recording.transcript_completed`)
- **Endpoint URL**: `https://<YOUR_HOST>/integrations/zoom/webhook`

Zoom will also run **URL validation** (`endpoint.url_validation`) during setup.

---

## 2) Environment variables (app)

These map to `ZoomSettings` in `configs/settings.py`.

| Variable | Description | Where to get it |
|---|---|---|
| `ZOOM_ACCOUNT_ID` | Zoom account id for S2S OAuth | Zoom App details |
| `ZOOM_CLIENT_ID` | S2S OAuth client id | Zoom App credentials |
| `ZOOM_CLIENT_SECRET` | S2S OAuth client secret | Zoom App credentials |
| `ZOOM_WEBHOOK_SECRET_TOKEN` | Secret token for URL validation / signature verification | Zoom app webhook config |

For local dev, set these in `configs/secrets/.env`.

---

## 3) How the webhook handler behaves (important edge cases)

### 3.1 Zoom 3-second timeout and duplicate webhooks

Zoom expects your endpoint to return `200` quickly. Transcript generation can take minutes.

In this repo, `POST /integrations/zoom/webhook` now queues background processing (FastAPI background tasks) and immediately returns:

```json
{ "status": "received", "queued": true }
```

### 3.2 Meeting UUID encoding (400 Bad Request)

Zoom recording APIs frequently require the **meeting UUID** (not the numeric meeting ID). UUIDs containing `/` must be **double URL-encoded**. The code handles this in the Zoom client/webhook handler.

### 3.3 File download auth and redirects (401 Unauthorized)

For transcript file downloads, some Zoom URLs redirect to other domains (e.g., S3). Authorization headers may be dropped on cross-domain redirect, causing 401s.

The code downloads using an access token injected via the **query string** (`?access_token=`) for those URLs.

---

## 4) Opportunity ID mapping (topic convention)

The handler extracts an opportunity id from the meeting **topic** using the canonical format:

- `oid123`
- `oid1234`

If no match is found, ingestion is skipped.

**Action:** ensure meeting topics include an identifier like `oid999`.

---

## 5) Local testing

### Option A — send a mock webhook payload

1. Start the API:

```powershell
cd "C:\path\to\Knowledge-Assist"  # repo root (folder name may differ locally)
uv run python main.py
```

2. In another terminal:

```powershell
uv run python scripts/test_zoom_webhook.py
```

### Option B — end-to-end test with ngrok

1. Start the API (pick your port, example 8080):

```powershell
uv run python main.py
```

2. Start ngrok (same port as API):

```powershell
ngrok http 8080
```

3. In Zoom App Marketplace, set the event notification endpoint to:

`https://<ngrok-host>/integrations/zoom/webhook`

4. Start a Zoom meeting, set topic like:

`Customer Sync oid999`

5. Enable **Record to Cloud**, wait a few seconds, end meeting.
6. Watch API logs:
   - URL validation responses (if Zoom tests)
   - retries while transcript becomes available
   - GCS writes when download succeeds

---

## 6) Cloud Run deployment notes

- Ensure `GCS_BUCKET_INGESTION` and GCS permissions are set (same ingestion bucket used by Slack/Drive).
- Store Zoom secrets in Secret Manager and mount as env vars on Cloud Run.
- Make sure the Cloud Run service is publicly reachable by Zoom (or allowlisted / through a gateway).

---

## 7) Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Zoom says URL validation failed | `ZOOM_WEBHOOK_SECRET_TOKEN` missing or wrong | set token, redeploy, revalidate |
| Multiple duplicate webhooks | endpoint slow / timeouts | ensure background tasks; check Cloud Run timeout |
| 400/404 for recordings lookup | UUID encoding issues | ensure latest code deployed |
| Nothing written to GCS | topic doesn’t include `oid###` | rename meeting topic, retest |

