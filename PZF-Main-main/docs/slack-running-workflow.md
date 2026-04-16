# Slack: end-to-end runbook (API, OAuth, sync to GCS)

This doc is the **step-by-step** flow: start the app, connect Slack once, trigger sync, and what changes on **second and later** runs.

> If you also use `POST /slack/discover` (auto-onboarding from channel names), see the **Discovery** section below.

---

## Prerequisites (once per environment)

| Requirement | Notes |
|-------------|--------|
| Postgres schema | Apply modular schema with `uv run python scripts/db/apply_modular_schema.py`, then verify with `uv run python scripts/db/check_schema_drift.py` |
| Slack OAuth | `users.slack_access_token` must be populated by OAuth |
| Slack app Redirect URL | Must include full callback path: `/oauth/slack/callback` |
| Env | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `GCS_BUCKET_INGESTION`, DB vars, GCP credentials |

---

## 1) Start the API (local)

```powershell
uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

---

## 2) Connect Slack (first time per user/workspace)

1) Get OAuth URL:

```powershell
$base = "http://127.0.0.1:8080"
$redirect = [uri]::EscapeDataString("https://YOUR-NGROK.ngrok-free.app/oauth/slack/callback")
$email = [uri]::EscapeDataString("you@company.com")
Invoke-RestMethod -Uri "$base/auth/slack/url?redirect_uri=$redirect&user_email=$email"
```

2) Open the returned `auth_url` in your browser and click **Allow**.

3) Verify DB: `users.slack_access_token` is set for that email.

---

## 3) Create DB rows (two options)

### Option A — Explicit (one opportunity)

```http
POST /opportunities/slack
Content-Type: application/json

{
  "oid": "oid1023",
  "name": "Customer deal name",
  "owner_email": "you@company.com"
}
```

### Option B — Discovery (Drive-style)

```http
POST /slack/discover
```

- Uses the connector user’s token (first user with `slack_access_token`, or `SLACK_CONNECTOR_USER_EMAIL` if set).
- Lists channels and upserts `opportunities` + `opportunity_sources(source_type='slack')`.

---

## 4) Channel naming rule (important)

Slack sync does **not** take channel names as API parameters.

For each opportunity, Slack channels must **start with** the alphanumeric-lowercased prefix derived from `opportunities.opportunity_id`.

Example:
- `opportunities.opportunity_id = oid1023`
- prefix = `oid1023`
- valid channel names: `oid1023-general`, `oid1023-security`

---

## 5) Pull messages to GCS (any time)

To fetch latest Slack messages and write to GCS:

```http
POST /sync/trigger
```

Or (recommended for scheduler):

```http
POST /sync/run
```

`/sync/run` executes: **Slack discover → Drive discover → sync**.

---

## What changes on second and later runs?

- **OAuth**: usually **no** (unless token revoked / different workspace/user).
- **DB onboarding**:
  - If using `POST /slack/discover`, run it anytime you create new channels / new OIDs and want DB rows created automatically.
  - If you use `POST /opportunities/slack`, you only call it for brand new OIDs (idempotent).
- **Sync**: yes — run `POST /sync/trigger` (or let scheduler call `/sync/run`) whenever you want new messages pulled.

