# Knowledge-Assist API — endpoint reference

Base URL examples:

- Local: `http://127.0.0.1:8080` (or the port in `APP` / `uvicorn` config)
- Cloud Run: `https://<your-service>.run.app`

**Interactive docs:** `GET /docs` (Swagger UI), `GET /redoc`, `GET /openapi.json`.

**Auth:** Many routes need a DB-backed user and OAuth tokens (Google `google_refresh_token`, Slack `slack_access_token`, etc.). For private Cloud Run, callers often send `Authorization: Bearer <identity-or-jwt-token>`.

---

## 1. Root app (`main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/google/callback` | **Browser OAuth redirect** from Google. Query: `code` (required), `error` optional. Exchanges code for tokens. |
| GET | `/oauth/slack/callback` | **Browser OAuth redirect** from Slack. Query: `code`, `state` (must carry `user_email`), `error` optional. |
| GET | `/questions` | Lists **all** SASE questions with section/subsection, `answer_type`, `requirement_type`, `option_values` (picklist). **No body.** Requires PostgreSQL (`sase_questions`, `sase_batches`, `sase_picklist_options`). |
| POST | `/answer-generation` | Runs the **answer-generation RAG pipeline** (same contract as the legacy Cloud Function). **JSON body** — see below. |

### `GET /questions`

- **Input:** none.
- **Response:** `{ "questions": [ { "question_id", "question_text", "answer_type", "requirement_type", "section", "subsection", "option_values": [] }, ... ] }`

### `POST /answer-generation`

- **Input (JSON):** At minimum includes `opportunity_id` and `retrievals` (per `AnswerGenerationPipeline` / your RAG contract). Exact shape matches production answer-generation service.

**Example (illustrative — align with your pipeline validation):**

```json
{
  "opportunity_id": "oid1234",
  "retrievals": {}
}
```

---

## 2. Auth (`/auth`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| GET | `/auth/google/url` | Query: **`redirect_uri`** (required) — must match Google Cloud Console OAuth redirect. | Returns `{ "auth_url": "<Google consent URL>" }` for SPA/backend to redirect the user. |
| POST | `/auth/google/callback` | **JSON body:** `{ "code": "<from Google>", "redirect_uri": "<same as token request>", "user_email": null }` | Exchanges authorization **code** for tokens; stores/refreshes user in DB. |
| GET | `/auth/slack/url` | Query: **`redirect_uri`** (required), **`user_email`** (optional but recommended — sent as OAuth `state`). | Returns `{ "auth_url": "<Slack OAuth URL>" }`. |
| POST | `/auth/slack/callback` | **JSON body:** `{ "code", "redirect_uri", "user_email": "<required for Slack attach>" }` | Exchanges Slack code; attaches `slack_access_token` to the user identified by `user_email`. |

**Example — GET Google URL**

```http
GET /auth/google/url?redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fauth%2Fgoogle%2Fcallback
```

**Example — POST Google callback**

```json
{
  "code": "4/0A...",
  "redirect_uri": "http://localhost:8080/auth/google/callback"
}
```

---

## 3. Opportunities (`/opportunities`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/opportunities/slack` | JSON: `EnsureSlackOpportunityBody` | Ensures `opportunities` + `opportunity_sources` (`slack`). Idempotent. |
| POST | `/opportunities/gmail` | JSON: `EnsureSourceBody` | Ensures `opportunities` + `opportunity_sources` (`gmail`). Owner must have **Google** OAuth. |
| GET | `/opportunities/{opportunity_id}/questions` | Path: `opportunity_id` (e.g. `oid1234`) | All questions from `sase_questions` + active answers + conflicts + `answer_type` / `requirement_type` / `option_values`. |
| POST | `/opportunities/{opportunity_id}/answers` | JSON: nested `q_id` updates **or** flat `SaveOrResolveAnswersInput` | Inserts answers, resolves conflicts, optional **user override** text (`is_user_override` + `override_value`). See OpenAPI examples in `/docs`. |
| GET | `/opportunities/{oid}/answers` | Path: `oid` | Grouped answers per question; `answer_type`/`requirement_type`; `answer_id`; citations; conflicts. |

### POST `/opportunities/slack`

```json
{
  "opportunity_id": "oid1234",
  "name": "Acme deal",
  "owner_email": "you@company.com"
}
```

### POST `/opportunities/gmail`

```json
{
  "opportunity_id": "oid1234",
  "name": "Acme deal",
  "owner_email": "you@company.com"
}
```

### GET `/opportunities/{opportunity_id}/questions`

- **Input:** path only.
- **Response:** `LoadQuestionsResponse` — `opportunity_id`, `questions[]` with `question_id`, `question_text`, `answer_type`, `requirement_type`, `option_values`, `final_answer_id`, `answers`, `conflict`.

### POST `/opportunities/{opportunity_id}/answers`

Two supported shapes (see **`/docs`** for full examples):

**A) Nested updates (one or many `q_id` objects):**

```json
{
  "updates": [
    {
      "q_id": "QID-001",
      "answer_id": "00000000-0000-0000-0000-000000000000"
    }
  ]
}
```

**Conflict resolution:**

```json
{
  "updates": [
    {
      "q_id": "QID-001",
      "conflict_id": "conflict-uuid",
      "conflict_answer_id": "chosen-answer-uuid"
    }
  ]
}
```

**User-edited final text (override):**

```json
{
  "updates": [
    {
      "q_id": "QID-001",
      "answer_id": "answer-uuid",
      "is_user_override": true,
      "override_value": "Corrected answer text from the user"
    }
  ]
}
```

If `is_user_override` is `true`, **`override_value` is required** (non-empty).

**B) Flat legacy shape:** `question_id`, `action` (`INSERT` | `RESOLVE`), `answers[]`, `selected_answer_id` as documented in `SaveOrResolveAnswersInput`.

### GET `/opportunities/{oid}/answers`

- **Input:** path `oid` (canonical or legacy GCS key — server resolves candidates).
- **Response:** `{ "opportunity_id", "answers": [ { "question_id", "answer_id", "answer_type", "requirement_type", "answer_value", "confidence_score", "citations", "conflict_id", "conflicts" } ] }`

---

## 4. Drive (`/drive`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/drive/discover` | **No body** | Lists folders under configured Drive root (`DRIVE_ROOT_FOLDER_NAME`); parses OID from folder names; upserts `opportunities` + `opportunity_sources` for **`drive`** and **`gmail`** (when missing). |

**Environment:** `DRIVE_ROOT_FOLDER_NAME`, Google OAuth, optional `DRIVE_CONNECTOR_USER_EMAIL`.

**Response (fields include):** `connector_user_email`, `drive_root_folder_name`, `folders_total`, `folders_parsed`, `opportunities_created`, `opportunity_sources_created`, **`gmail_sources_created`**, `skipped`.

---

## 5. Gmail (`/gmail`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/gmail/discover` | **No body** | Gmail search union (`GMAIL_DISCOVER_QUERY` + fallbacks); finds threads whose **subject** contains an OID; upserts `opportunities` + `opportunity_sources` (`gmail`). |

**Environment:** `GMAIL_DISCOVER_QUERY`, `GMAIL_DISCOVER_MAX_THREADS`, `GMAIL_CONNECTOR_USER_EMAIL` / `DRIVE_CONNECTOR_USER_EMAIL`, Google OAuth.

---

## 6. Slack (`/slack`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/slack/discover` | **No body** | Scans Slack channels; matches channel name prefix to OID; upserts `opportunities` + `opportunity_sources` (`slack`). |

**Requires:** Slack connector user with `slack_access_token`.

---

## 7. Sync (`/sync`)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/sync/trigger` | **No body** | Runs **all** `opportunity_sources` plugins in parallel (up to `SYNC_MAX_WORKERS`): Gmail, Slack, Drive, Zoom → raw GCS where applicable. Returns per-source `items_synced`. |
| POST | `/sync/run` | **No body** | **Order:** `POST /slack/discover` → `POST /gmail/discover` → `POST /drive/discover` → then **same** as `/sync/trigger`. |

**Environment:** `SYNC_MAX_WORKERS`, OAuth and connector settings per plugin.

**Response `/sync/trigger`:** `status`, `message`, `sources_total`, `items_total`, `results[]` (`opportunity_id`, `source_type`, `source_id`, `items_synced`, `ok`, `error`).

**Response `/sync/run`:** `slack_discover`, `gmail_discover`, `drive_discover`, `sync` (payload as `/sync/trigger`).

---

## 8. Zoom (no router prefix)

| Method | Path | Input | What it does |
|--------|------|-------|----------------|
| POST | `/zoom/discover` | Query: **`days_lookback`** (optional, default `14`, max `90`) | Lists Zoom cloud recordings; parses OID from **meeting topic**; upserts `opportunities` + `opportunity_sources` (`zoom`). |
| POST | `/integrations/zoom/webhook` | **Raw JSON body** (Zoom webhook payload); headers `x-zm-signature`, `x-zm-request-timestamp` for verification | URL validation challenge; async processing of recording events. |

**Example:**

```http
POST /zoom/discover?days_lookback=14
```

---

## 9. Cloud Functions entrypoints (`main.py`)

These are **not** mounted on the FastAPI `app` for local HTTP; they target Google Cloud Functions / Cloud Run with **Functions Framework**:

| Decorator | Purpose |
|-----------|---------|
| `@functions_framework.cloud_event` `rag_ingestion` | Pub/Sub → RAG ingestion handler |
| `@functions_framework.http` `pubsub_dispatch` | HTTP pubsub dispatch |
| `@functions_framework.http` `gcs_file_processor` | GCS event processing |

Deploy/configure per `functions/` modules and your GCP setup.

---

## Quick reference — method summary

| Method | Endpoint |
|--------|----------|
| GET | `/auth/google/callback`, `/oauth/slack/callback`, `/questions` |
| GET | `/auth/google/url`, `/auth/slack/url` |
| POST | `/auth/google/callback`, `/auth/slack/callback` |
| POST | `/answer-generation` |
| POST | `/opportunities/slack`, `/opportunities/gmail` |
| GET | `/opportunities/{opportunity_id}/questions` |
| POST | `/opportunities/{opportunity_id}/answers` |
| GET | `/opportunities/{oid}/answers` |
| POST | `/drive/discover`, `/gmail/discover`, `/slack/discover` |
| POST | `/sync/trigger`, `/sync/run` |
| POST | `/zoom/discover`, `/integrations/zoom/webhook` |

---

*Generated from the FastAPI routers in this repository. For field-level validation and additional examples, use **Swagger UI** at `/docs`.*
