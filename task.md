# Knowledge-Assist Plugins Integration Tasks

## Phase 1: Authentication & Database Models
- [x] Create `src/services/database` structure for Cloud SQL PostgreSQL connection (SQLAlchemy setup).
- [x] Define SQLAlchemy database models (`models.py`) to hold OAuth credentials (Google, Slack, Zoom).
- [x] Implement `src/services/plugins/oauth_service.py` to handle generic token generation, refresh, and DB storage.
- [x] Create `src/apis/routes/auth_routes.py` for OAuth callback endpoints (Google and Slack).

## Phase 2: Plugin Services (Data Extraction)
- [x] Create `src/services/plugins/gmail_plugin.py` with Gmail API fetching and body cleaning logic.
- [x] Create `src/services/plugins/slack_plugin.py` with incremental cursor-based polling logic.
- [x] Create `src/services/plugins/drive_plugin.py` with modifiedTime sync tracking.
- [x] Create `src/services/plugins/zoom_plugin.py` with Server-to-Server OAuth fetching for transcripts.

## Phase 3: Sync Orchestration
- [x] Create `src/apis/routes/sync_routes.py` for the unified Cloud Scheduler CRON trigger (`POST /sync/trigger`).
- [x] Integrate plugin services into the sync endpoint to fetch data and write to GCS `raw/`.
- [x] Update `main.py` routing to include `auth_routes` and `sync_routes`.
- [x] Update `requirements.txt` / `uv.lock` with necessary dependencies (e.g. `google-api-python-client`, `slack_sdk`, `SQLAlchemy`, etc.).
