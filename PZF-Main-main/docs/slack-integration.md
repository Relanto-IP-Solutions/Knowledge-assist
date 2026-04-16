# Slack Integration — OAuth, Sync & GCS Pipeline

Complete guide for connecting Slack workspaces, syncing messages to GCS, and running the end-to-end pipeline.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Database** | Run `uv run python scripts/db/apply_modular_schema.py` to apply modular schema (`users`, `opportunities`, `opportunity_sources`, and related tables). Use `uv run python scripts/db/check_schema_drift.py` to verify no manual drift. |
| **User row** | Email must match what you pass as `user_email` in OAuth |
| **Opportunity source** | At least one row with `source_type = 'slack'` for the opportunity |
| **Slack app** | OAuth & Permissions → Redirect URLs must include the full callback URL |
| **Environment** | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `GCS_BUCKET_INGESTION`, GCP credentials, `DATABASE_URL` |

---

## 1. Database Setup

### Plugin Tables

The API relies on modular SQL schema managed under `db/schema/modules`.

**Create tables:**

```powershell
uv run python scripts/db/apply_modular_schema.py
uv run python scripts/db/check_schema_drift.py
```

### Seed Data (if not using API)

```sql
INSERT INTO users (email, name, slack_access_token)
VALUES ('you@company.com', 'Your Name', NULL)
ON CONFLICT (email) DO NOTHING;

INSERT INTO opportunities (opportunity_id, name, owner_id)
SELECT 'oid1023', 'Test opportunity', id FROM users WHERE email = 'you@company.com'
ON CONFLICT (opportunity_id) DO NOTHING;

INSERT INTO opportunity_sources (opportunity_id, source_type)
SELECT o.id, 'slack' FROM opportunities o WHERE o.opportunity_id = 'oid1023';
```

---

## 2. Slack Channel Naming Convention

Slack channels are discovered by name prefix matching. The API does **not** take channel names as parameters.

| Concept | How it works |
|---------|--------------|
| **OID prefix** | `opportunities.opportunity_id` → lowercase alphanumeric prefix. Example: `oid1023` → `oid1023` |
| **Channel naming** | Create Slack channels starting with the prefix: `oid1023-general`, `oid1023-technical` |
| **Bot access** | Invite the Slack app/bot to private channels |

---

## 3. HTTPS Redirect with ngrok

Slack requires HTTPS for OAuth redirects. Use ngrok for local development.

### Start ngrok

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abcd-1234.ngrok-free.app`).

### Configure Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → your app → **OAuth & Permissions**
2. Under **Redirect URLs**, add the **full callback path**:

   ```
   https://YOUR-NGROK.ngrok-free.app/oauth/slack/callback
   ```

   > **Important:** Include the path `/oauth/slack/callback`, not just the hostname.

3. Save URLs

### ngrok Free Tier

- Hostname changes on each restart (update Slack Redirect URLs accordingly)
- Reserved domains available on paid plans

---

## 4. OAuth Flow

### 4a. Start the API

```powershell
uv run python main.py
```

Leave this terminal open. Default: `http://127.0.0.1:8000`

### 4b. Get Authorization URL

```powershell
$base = "http://127.0.0.1:8000"
$redirect = [uri]::EscapeDataString("https://YOUR-NGROK.ngrok-free.app/oauth/slack/callback")
$email = [uri]::EscapeDataString("you@company.com")
Invoke-RestMethod -Uri "$base/auth/slack/url?redirect_uri=$redirect&user_email=$email"
```

Response:

```json
{
  "auth_url": "https://slack.com/oauth/v2/authorize?..."
}
```

### 4c. Authorize in Browser

Open `auth_url` in a browser → Click **Allow** in Slack.

### 4d. Callback Handling

Slack redirects to your callback URL. The app handles `GET /oauth/slack/callback` and returns:

```json
{
  "ok": true,
  "message": "Slack workspace connected securely."
}
```

This updates `users.slack_access_token` with the bot token (`xoxb-...`).

> **Note:** The OAuth `code` is single-use. If something fails, restart from step 4b.

---

## 5. API Reference

Import the Postman collection: [`docs/postman/Knowledge-Assist-Slack.postman_collection.json`](./postman/Knowledge-Assist-Slack.postman_collection.json)

FastAPI docs available at `GET /docs` when the server is running.

### POST /opportunities/slack — Create Opportunity + Slack Source

Creates database rows for a new opportunity with Slack integration.

| Field | Required | Description |
|-------|----------|-------------|
| `oid` | Yes | Unique opportunity ID (drives GCS path and channel prefix matching) |
| `name` | Yes | Human-readable opportunity name |
| `owner_email` | Yes | Existing user email (must have completed OAuth) |

**Request:**

```json
{
  "oid": "oid1023",
  "name": "Customer deal name",
  "owner_email": "you@company.com"
}
```

**Success (200):**

```json
{
  "opportunity_id": 3,
  "oid": "oid1023",
  "name": "Customer deal name",
  "owner_id": 1,
  "slack_source_id": 5,
  "opportunity_created": true,
  "slack_source_created": true
}
```

**When to call:**

| Situation | Call this endpoint? |
|-----------|---------------------|
| New opportunity that should use Slack | Yes |
| Opportunity exists but missing `slack` source | Yes (idempotent) |
| New Slack channel for existing opportunity | No — just `POST /sync/trigger` |
| New messages in existing channels | No — just `POST /sync/trigger` |

### POST /sync/trigger — Sync All Sources to GCS

Pulls data from all configured sources (Slack, Gmail, Drive, Zoom) and writes to GCS.

**Request:** No body required.

**Response (200):**

```json
{
  "status": "completed",
  "message": "Processed 2 source(s); 26 item(s) pushed to raw GCS tier.",
  "sources_total": 2,
  "items_total": 26,
  "results": [
    {
      "opportunity_id": "oid1023",
      "source_type": "slack",
      "source_id": 1,
      "items_synced": 16,
      "ok": true,
      "error": null
    }
  ]
}
```

### GET /auth/slack/url — Get OAuth URL

| Parameter | Description |
|-----------|-------------|
| `redirect_uri` | URL-encoded callback URL (must match Slack app config) |
| `user_email` | URL-encoded email of user in `users` table |

### GET /oauth/slack/callback — OAuth Redirect Handler

Called by Slack after user authorizes. Returns JSON with `ok: true` on success.

---

## 6. End-to-End Workflow

### First Time Setup

1. **Start API:** `uv run python main.py`
2. **Start ngrok:** `ngrok http 8000` (in second terminal)
3. **Get OAuth URL:** `GET /auth/slack/url?redirect_uri=...&user_email=...`
4. **Authorize:** Open `auth_url` in browser, click Allow
5. **Create opportunity:** `POST /opportunities/slack` with `oid`, `name`, `owner_email`
6. **Trigger sync:** `POST /sync/trigger`
7. **Verify:** Check GCS bucket at `{OID}/raw/slack/`

### Subsequent Runs

| Situation | Action |
|-----------|--------|
| Pull latest messages | `POST /sync/trigger` only |
| New opportunity | `POST /opportunities/slack`, then `POST /sync/trigger` |
| New Slack workspace or revoked token | Re-run OAuth flow |
| Cron/automation | Schedule `POST /sync/trigger` |

---

## 7. GCS Output Structure

After sync, files appear at:

```
gs://{GCS_BUCKET_INGESTION}/{opportunity_id}/raw/slack/
├── slack_metadata.json
└── {channel_id}/
    └── slack_messages.json
```

---

## 8. Troubleshooting

### Storage read failed / IndexError

**Cause:** `GCS_BUCKET_INGESTION` is empty or not set.

**Fix:**
1. Set `GCS_BUCKET_INGESTION` in `configs/.env` or `configs/secrets/.env`
2. Ensure GCP credentials can access the bucket
3. Restart the API
4. Run `POST /sync/trigger` again (OAuth does not need to be repeated)

### OAuth code already used

The `code` parameter is single-use. Start the OAuth flow again from `GET /auth/slack/url`.

### Redirect URL mismatch

Ensure the `redirect_uri` parameter **exactly** matches what's configured in Slack app settings, including the full path `/oauth/slack/callback`.

### No channels found

- Verify Slack channel names start with the OID prefix (lowercase, alphanumeric only)
- Ensure the bot is invited to private channels

---

## 9. Verification Checklist

- [ ] `users.slack_access_token` is set (`xoxb-...`)
- [ ] `opportunity_sources` has row with `source_type = 'slack'`
- [ ] Slack channels follow OID prefix naming
- [ ] Bot is invited to private channels
- [ ] GCS objects exist at `{OID}/raw/slack/`

**Smoke test:**

```powershell
uv run python scripts/tests_integration/smoke_slack_gcs_pipeline.py
```
