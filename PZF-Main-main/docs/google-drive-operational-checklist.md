# Google Drive → GCS: production checklist (user OAuth, `raw/documents/`)

This document expands **every operational step** for the **existing** integration: **end-user Google OAuth** (not a Drive service account), Drive folders per opportunity `**oid`**, sync via `**POST /sync/trigger**`, objects under `**gs://{bucket}/{OID}/raw/documents/**`.

Code references: `src/services/plugins/oauth_service.py` (Google OAuth URL + token exchange), `src/services/plugins/drive_plugin.py` (Drive sync), `src/apis/routes/auth_routes.py` (`/auth/google/url`, `/auth/google/callback`).

---

## OAuth (user) vs service account on Drive — which is better for production?


| Dimension                               | **Current approach: user OAuth + refresh token**                                                                       | **Service account (SA) on Drive**                                                                                                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Who owns the data in Google’s model** | The **end user**; they **consent** to your app reading their Drive.                                                    | A **robot identity**; users must **share** each folder with the SA email (or use Shared drives + membership).                                                                     |
| **Multi-tenant SaaS**                   | **Strong fit:** each customer signs in with Google; token tied to **their** account. Revocation is per user at Google. | **Possible** but **operationally heavy:** every new folder must be shared with the SA (or you use **domain-wide delegation** for Google Workspace — admin-only, security review). |
| **Compliance / audit**                  | Clear story: “user granted read-only Drive access.”                                                                    | Clear for **central IT–owned** corpora; murkier when many external users must share folders with an SA.                                                                           |
| **Implementation in this repo**         | **Implemented:** `users.google_refresh_token` + `drive_plugin`.                                                        | **Not implemented** for Drive; would require new auth path (SA JSON + Drive API as SA).                                                                                           |
| **GCS**                                 | Still uses **GCP service account or ADC** for bucket access — **separate** from Drive.                                 | Same for GCS; only the **Drive** side changes.                                                                                                                                    |


**Recommendation for most production SaaS products:** keep **user OAuth for Drive** (this repo’s approach). Use a **service account for GCS** only (`GOOGLE_APPLICATION_CREDENTIALS`), which you already do for ingestion.

Use **Drive service accounts** when a **single org** owns all files, IT can **standardize** on “share to `svc-xxx@...`”, or you run on **Workspace** with **domain-wide delegation** and accept the admin/security overhead.

---

## A. Google Cloud (OAuth for Drive — Web client, consent, scopes)

### A1. Create or select a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select an existing project or **Create project**; note the **Project ID**.

### A2. Enable APIs used by the app

1. **APIs & Services → Library**.
2. Enable **Google Drive API** (required for listing/downloading files).
3. Enable **Gmail API** only if you use Gmail ingestion; the **same** OAuth flow in this codebase requests **both** `drive.readonly` and `gmail.readonly` in one authorization (see `oauth_service.get_google_auth_url`). If you do not need Gmail, you may later narrow scopes in code; as shipped, enable **Gmail API** too to avoid confusing errors during token exchange.

### A3. OAuth consent screen (where **scopes** are added — do this **before** you rely on sign-in)

**Do you need to “create” scopes?** No. Scopes are **predefined strings** from Google. You **select** them on the consent screen so Google allows your app to **request** them. Your Python code already **requests** the same list in `oauth_service.get_google_auth_url` — the consent screen list should **match** that.

**Order:** Configure **OAuth consent screen** (including scopes) **before** or **along with** creating the OAuth client. You can create the **Web client ID** first, but sign-in will not work cleanly until scopes and (for External) **test users** are set.

1. **APIs & Services → OAuth consent screen**.
2. Choose **User type**:
  - **Internal** (Google Workspace only, same org): faster for internal tools.
  - **External**: for any `@gmail.com` or outside users; while **Publishing status = Testing**, only **test users** can sign in.
3. **App information:** **App name**, **User support email**, **Developer contact** → **Save and Continue**.
4. **Scopes —** click **Edit app** → **Scopes** (or during first-time wizard: **Scopes** step) → **Add or remove scopes**:
  This is the **only** place in the Console where you “add scopes” for the **consent screen**. Add everything your app requests in code:

  | Scope (add in Google’s picker or “Manually add scopes”)                         |     |
  | ------------------------------------------------------------------------------- | --- |
  | `openid`                                                                        |     |
  | `https://www.googleapis.com/auth/userinfo.email` (often shown as **email**)     |     |
  | `https://www.googleapis.com/auth/userinfo.profile` (often shown as **profile**) |     |
  | `https://www.googleapis.com/auth/drive.readonly`                                |     |
  | `https://www.googleapis.com/auth/gmail.readonly`                                |     |

   **Save and Continue**.
5. **Test users** (required if **External** and status is **Testing**): **Add users** → enter every Google account that will sign in (e.g. your `@gmail.com`). Accounts **not** listed get `access_denied` / `403`.
6. **Summary** → **Back to Dashboard**.

**Why “scope mismatch”?** If the consent screen omits a scope that your app puts on the authorize URL, consent or token exchange can fail. Keep A3 aligned with `oauth_service.py`.

**Production / verification:** Drive and Gmail readonly scopes are often **sensitive**. For broad public use, Google may require **app verification** (can take significant time). Plan for internal/testing first.

### A4. OAuth 2.0 Client ID (Web application) — **yes, you create this**

This is **separate** from scopes. The **OAuth client** provides **Client ID** and **Client secret** for `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. It does **not** list scopes; scopes are on the **consent screen** (A3).

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. If asked, **Configure consent screen** first (complete A3).
3. Application type: **Web application** → name it (e.g. `Knowledge-Assist local`).
4. **Authorized JavaScript origins** — **when to use `http://localhost:5173`**
  - Add `**http://localhost:5173**` only if your **browser** app (e.g. Vite/React) is served from that URL and Google redirects back to a page on that origin.
  - Format: **origin only** — `http://localhost:5173` (no path, no trailing slash).
  - If you **do not** use a frontend on 5173, do **not** add it; use the origin you actually use (e.g. `http://localhost:3000`) or a Postman OAuth redirect.
5. **Authorized redirect URIs** — **not** the FastAPI server URL
  Google redirects the **browser** here with `**GET ?code=...`**. This URI must be **exactly** the same string you pass as `**redirect_uri`** to `**GET /auth/google/url?redirect_uri=...**` and again in `**POST /auth/google/callback**` JSON.
   Typical **Vite dev** SPA:
  - **Authorized redirect URIs:** `http://localhost:5173/auth/google/callback`  
  (only if your SPA implements that route and you use that exact string in the API calls.)
   **No SPA:** use Postman’s OAuth redirect (`https://oauth.pstmn.io/v1/callback`) or another URI you register; **same** string everywhere.
6. **Create** → copy **Client ID** and **Client secret** (store the secret safely).

### A5. Put credentials in project env

1. In this repo, settings load `**configs/.env`** and `**configs/secrets/.env**` (see `configs/settings.py`).
2. Set:
  ```env
   GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<your-client-secret>
  ```
3. **Restart** the API after changes.

### A6. Refresh token and `prompt=consent` — what it means (you don’t “run” a separate command)

In `oauth_service.get_google_auth_url` the app adds:

- `**access_type=offline`** — asks Google for a **refresh token** so the server can obtain new access tokens later without the user clicking “Sign in” again.
- `**prompt=consent`** — forces the consent screen to appear so Google is more likely to return a **refresh token** (especially important the first time or when scopes change).

**What you do in practice**

1. Complete the Google sign-in flow **once** through your app (open `auth_url` → sign in → approve → your app receives `code` → `**POST /auth/google/callback`** succeeds).
2. Check the database: `**users.google_refresh_token**` should be **non-null** for that user.
3. **You do not** run a separate script for A6 — it is **behavior inside** the generated `auth_url`.

**If `google_refresh_token` stays empty**

- User may have signed in before `**access_type=offline`** / `**prompt=consent**` were set — sign in again after revoking app access at [Google Account → Third-party access](https://myaccount.google.com/permissions) or use **prompt=consent** again.
- For the same user, Google may not return a new refresh token every time; revoking and re-authorizing often fixes it.

**Why it matters:** `drive_plugin` uses the refresh token to call Drive. No refresh token → refresh fails → sync uploads **0** files.

---

## B. User and database

### B1. User row and Google OAuth

1. **Sign-in flow (typical):**
  - Frontend calls `**GET /auth/google/url?redirect_uri=<URL_ENCODED_CALLBACK>`**.
  - Response: `{ "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }`.
  - User opens `auth_url`, signs in, grants access.
  - Google redirects to your `**redirect_uri**` with `?code=...`.
  - Frontend calls `**POST /auth/google/callback**` with JSON:
    ```json
    {
      "code": "<authorization_code>",
      "redirect_uri": "<exact same redirect_uri as in step 1>"
    }
    ```
2. **Backend behavior** (`exchange_google_code`):
  - Exchanges `code` for tokens.
  - Verifies ID token; reads **email**.
  - Creates `**users`** row if missing, or updates existing.
  - Saves `**users.google_refresh_token**` when Google returns it.
3. **Same Google account as Drive:** Files must live in **My Drive** (or a Shared drive) **visible to that Google user**. The integration reads **that user’s** Drive using their token.

#### B1a. Localhost: exact GET and POST (copy-paste)

**Prerequisites**

- API running (e.g. `uv run python main.py`). Default port is **8000** unless you set **`APP_PORT`** (e.g. `8080`). Below, replace **`API_BASE`** with `http://127.0.0.1:8000` or your real host/port.
- **`GOOGLE_CLIENT_ID`** / **`GOOGLE_CLIENT_SECRET`** set; restart API after changes.
- In **Google Cloud → OAuth client (Web)**, **Authorized redirect URIs** includes the **`REDIRECT_URI`** you use below **exactly** (same scheme, host, port, path).
- **`REDIRECT_URI`** is where **Google’s browser redirect** lands (usually your **frontend**). This repo’s backend does **not** implement `GET /auth/google/callback`; Google never POSTs to you automatically—you (or your SPA) must call **`POST /auth/google/callback`** with the `code`.

**Pick one `REDIRECT_URI` string** (must match Google Console + both steps below). Example for Vite dev:

```text
http://localhost:5173/auth/google/callback
```

**Step 1 — GET authorize URL (from terminal or browser)**

**Request**

```http
GET {API_BASE}/auth/google/url?redirect_uri={URL_ENCODED_REDIRECT_URI}
```

**Query parameters**

| Parameter        | Required | Meaning |
|-----------------|----------|---------|
| `redirect_uri`  | Yes      | **Full** callback URL Google will redirect to; must be **percent-encoded** in the query string. |

**Example (PowerShell)**

```powershell
$API_BASE = "http://127.0.0.1:8000"
$REDIRECT_URI = "http://localhost:5173/auth/google/callback"
$enc = [uri]::EscapeDataString($REDIRECT_URI)
$step1 = Invoke-RestMethod -Uri "$API_BASE/auth/google/url?redirect_uri=$enc"
$step1.auth_url
```

**Response (200, JSON)**

```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...&redirect_uri=...&response_type=code&scope=...&access_type=offline&prompt=consent"
}
```

**Step 2 — Browser (human)**

1. Copy **`auth_url`** and open it in a browser (or `Start-Process $step1.auth_url` in PowerShell).
2. Sign in with Google and click **Allow**.
3. Google redirects to **`REDIRECT_URI?code=...&scope=...`** (HTTP **GET** to your frontend—or to whatever URI you registered).

**If you have no frontend yet:** register a redirect you control, or temporarily use a dev page that only shows the address bar. You need the **`code`** query parameter (short-lived, single-use).

**Step 3 — POST exchange code for tokens (backend)**

**Request**

```http
POST {API_BASE}/auth/google/callback
Content-Type: application/json
```

**Body (JSON)** — `user_email` is **not** used for Google (optional field on the model; omit it).

```json
{
  "code": "PASTE_THE_CODE_FROM_THE_BROWSER_ADDRESS_BAR",
  "redirect_uri": "http://localhost:5173/auth/google/callback"
}
```

**Critical:** `redirect_uri` here must be the **same decoded string** as in Step 1 (not double-encoded). Google’s token endpoint rejects mismatches.

**Example (PowerShell)** — after you copy `code` from the redirect URL:

```powershell
$code = "4/0A..."   # paste full code from ?code=
$body = @{
  code         = $code
  redirect_uri = $REDIRECT_URI
} | ConvertTo-Json

Invoke-RestMethod -Method POST -Uri "$API_BASE/auth/google/callback" -Body $body -ContentType "application/json; charset=utf-8"
```

**Success (200, JSON)** — shape from `exchange_google_code`:

```json
{
  "email": "you@gmail.com",
  "message": "Google authentication successful"
}
```

**Failure (400)** — body contains `detail` with the error string (e.g. token exchange failed, redirect mismatch).

**Step 4 — Verify refresh token (A6)**

- In Postgres, open **`users`** for that **`email`** and confirm **`google_refresh_token`** is **non-null**.
- If it is **null**, revoke the app under [Google Account → Third-party access](https://myaccount.google.com/permissions) and repeat Steps 1–3 so Google returns a new refresh token (`prompt=consent` is already in `auth_url`).

**`curl` equivalents**

```bash
# Step 1
curl -sS "http://127.0.0.1:8000/auth/google/url?redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fauth%2Fgoogle%2Fcallback"

# Step 3
curl -sS -X POST "http://127.0.0.1:8000/auth/google/callback" \
  -H "Content-Type: application/json" \
  -d '{"code":"PASTE_CODE","redirect_uri":"http://localhost:5173/auth/google/callback"}'
```

### B2. `opportunities` row

- Insert a row with unique `**oid`** (canonical: `oid1234`). This string is used:
  - In GCS: `{oid}/raw/documents/...`
  - In Drive search: folder **name contains** this substring (`drive_plugin`).

### B3. `opportunity_sources` row for Drive

- `**opportunity_id`**: FK to `opportunities.id`.
- `**source_type**`: `**'drive'**` (exact string used in `sync_routes.run_sync_job`).

Example SQL (adjust IDs):

```sql
INSERT INTO opportunity_sources (opportunity_id, source_type)
SELECT id, 'drive' FROM opportunities WHERE oid = 'oid1023'
ON CONFLICT DO NOTHING;
```

If you have no unique constraint on `(opportunity_id, source_type)`, run once or check for duplicates manually.

### B4. Opportunity owner

- `**opportunities.owner_id**` must point to the `**users**` row whose `**google_refresh_token**` is set (the person whose Drive you sync). If the wrong user owns the opportunity, `sync_drive_source` uses the wrong credentials.

---

## C. Google Drive (folder convention)

### C1. Folder naming (must match plugin search)

`drive_plugin` supports **two** folder conventions:

#### Option 1 (recommended for your requirement): one parent folder, then one subfolder per opportunity

Set:

```env
DRIVE_ROOT_FOLDER_NAME=Requirements
```

Optional (Shared Drives support; default is true in code):

```env
DRIVE_SUPPORTS_ALL_DRIVES=true
```

Then create a Drive folder tree like:

```text
Requirements/
  oid1023-general/
    <pdf/xlsx/docx/etc>
  oid1021/
    <pdf/xlsx/docx/etc>
```

The plugin will:

- find the parent folder whose name is exactly `DRIVE_ROOT_FOLDER_NAME`
- then find the **first** child folder under it whose name **contains** the opportunity `oid`
- then recursively sync all files under that child folder

#### Option 2 (legacy): search anywhere in Drive

If `DRIVE_ROOT_FOLDER_NAME` is empty, the plugin searches for any folder whose name contains the `oid` (anywhere the OAuth user can see).

---

**Exact query behavior**

When searching without a parent folder, `drive_plugin` uses:

```text
mimeType = 'application/vnd.google-apps.folder' and name contains '{opp.opportunity_id}' and trashed = false
```

So:

1. Create a **folder** in the **OAuth user’s** Drive (or a **Shared drive** where that user has access).
2. The folder **name** must **contain** the `**oid`** substring exactly as in the DB (e.g. `oid1023` or `Deal oid1023 - Acme`). **Case-sensitive** substring in API terms — use a consistent convention.
3. **Only the first** search result is used (`found_folders[0]`). Avoid duplicate folders whose names all contain the same `oid`.

### C2. No “bot invite” for Drive (user OAuth)

- You do **not** invite a Slack-style bot.
- The **authenticated Google user** is the principal. Anyone who puts files in that folder tree (shared editors) is fine; **listing** still uses the token owner’s permissions.

### C3. Shared Drive (Team Drive)

- Supported if the OAuth user is a member and has access to the folder. If your org uses **Shared drives**, ensure the folder is in a drive the user can read.

### C4. Upload files

- Upload **PDF**, **Excel `.xlsx`**, **Office files**, etc. **Subfolders** are scanned recursively.
- **Google Docs / Sheets / Slides**: exported as **PDF** in code (filename gets `.pdf` appended). Other Google app types may be **skipped**.

---

## D. GCS (ingestion bucket)

### D1. Bucket

- Set `**GCS_BUCKET_INGESTION`** to the bucket name (no `gs://` prefix) in `**configs/.env**` or `**configs/secrets/.env**`.

### D2. Credentials for GCS (not Drive)

- Set `**GOOGLE_APPLICATION_CREDENTIALS**` to a **GCP service account JSON** key path (often under `configs/secrets/`), **or** rely on **Application Default Credentials** where the app runs (e.g. Cloud Run default SA).
- Grant that identity **Storage Object Admin** (or equivalent) on `**GCS_BUCKET_INGESTION`**.
- `**GCP_PROJECT_ID**` should match the project that owns the bucket/client.

### D3. Path written by Drive sync

Objects are stored as:

```text
{opportunity_id}/raw/documents/{file_name}
```

i.e. `**raw/documents/**`, not `raw/docs/`.

---

## E. Scheduler (every 15 minutes)

### E1. What to call

- `**POST /sync/trigger**` (no body).
- Runs **all** opportunity sources (Gmail, Slack, Drive, Zoom) configured in the DB — not Drive-only. If you need Drive-only runs, that would require a **new** endpoint or filter (not in current code).

### E1a. Recommended automation for new Drive folders (no manual DB inserts)

If you want anyone to create a new folder under `Requirements/` (or your configured root) and have the system sync it automatically, use this two-step schedule:

1. `POST /drive/discover`  (discover folders → upsert DB)
2. `POST /sync/trigger`    (sync all sources → write to GCS)

`/drive/discover`:

- lists **direct subfolders** under `DRIVE_ROOT_FOLDER_NAME`
- extracts an opportunity id token from each folder name (e.g. `oid2345`)
- upserts:
  - `opportunities(oid, name, owner_id=<connector user>)`
  - `opportunity_sources(source_type='drive')`

**Env vars used**

- `DRIVE_ROOT_FOLDER_NAME` (required for discover)
- `DRIVE_CONNECTOR_USER_EMAIL` (optional; otherwise the first user with `google_refresh_token` is used)

**Important:** `/sync/trigger` already runs Slack/Gmail/Zoom/Drive for all DB sources. Adding `/drive/discover` before it only ensures the Drive sources exist for new folders.

### E2. Cloud Scheduler (GCP)

1. **Create job** → **Target: HTTP**.
2. **URL:** `https://<your-cloud-run-or-lb-host>/sync/trigger`.
3. **HTTP method:** `POST`.
4. **Frequency:** `*/15 * * * `* (every 15 minutes) or your cron string.
5. **Auth:**
  - **If public (dev only):** no auth — **not recommended** for production.
  - **Recommended:** protect with **IAM** (Scheduler OIDC token to Cloud Run **invoker**), **API key**, or **mTLS** — implement according to your deployment.

### E3. Local cron (dev)

```bash
# Example: every 15 minutes (Linux/macOS)
*/15 * * * * curl -sS -X POST http://127.0.0.1:8000/sync/trigger
```

Adjust host/port to match `**APP_HOST` / `APP_PORT**`.

### E4. Logs and HTTP response

- Sync **waits** until completion; response includes `**results`** per source with `**items_synced**` and `**opportunity_id**` (see `sync_routes`).
- Watch application logs for `Downloaded and uploaded ... from Drive` and errors.

---

## F. Verify

### F1. GCS `raw/documents`

1. Open **Cloud Console → Storage → bucket** (`GCS_BUCKET_INGESTION`).
2. Navigate: `**{OID}/raw/documents/`**.
3. Confirm new objects after upload + sync.

### F2. Checkpoint

- `**opportunity_sources.sync_checkpoint**` stores JSON `**{ drive_file_id: modifiedTime }**` for incremental sync. After a successful sync it should update.

#### When you need to reset the Drive checkpoint (rare, but important)

Normally you **never** touch `sync_checkpoint`. The connector uses it to skip files that have not changed in Drive.

You may need a one-time reset if a previous run could **read Drive** but could **not write to GCS** (common example: `GCS_BUCKET_INGESTION` was empty or credentials were wrong). In that situation, older versions of the connector could advance the checkpoint even though files were not actually uploaded; later runs would “skip” them.

**Symptoms**

- Drive log shows it found the correct folder (e.g. `Found root folder 'Requirements/oid1023...'`) but you do **not** see `Downloaded and uploaded ... from Drive`
- `POST /sync/trigger` response shows `source_type: drive` with `items_synced: 0` even though you added files
- GCS `raw/documents/` is missing expected files

**Fix (reset just the Drive source row for that opportunity)**

1. Find the `opportunity_sources.id` for `source_type='drive'` (you can also use the `source_id` in the `/sync/trigger` response).
2. Run:

```sql
UPDATE opportunity_sources
SET sync_checkpoint = NULL,
    last_synced_at = NULL
WHERE id = <DRIVE_SOURCE_ID>;
```

3. Re-run: `POST /sync/trigger`

After this, Drive will re-evaluate all files and upload anything missing/changed.

### F3. Downstream pipeline

- `**GcsPipeline**` / Pub/Sub / Cloud Functions (your deployment) should process `**raw/documents**` → `**processed/documents**` → ingestion. Confirm that pipeline is deployed and subscribed to the same bucket/prefixes.

### F4. Quick troubleshooting


| Symptom                                   | Check                                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------ |
| Drive sync **0 items**, “No Drive folder” | Folder **name contains** `oid`? Correct Google account?                  |
| **403** from Google                       | Token revoked; re-run Google OAuth.                                      |
| **GCS errors**                            | `GCS_BUCKET_INGESTION`, IAM on bucket, `GOOGLE_APPLICATION_CREDENTIALS`. |
| Wrong user’s Drive                        | `**opportunities.owner_id`** vs user who completed OAuth.                |


---

## One-page order of operations (first time)

1. GCP: project, enable APIs, OAuth consent, OAuth Web client, env vars `**GOOGLE_CLIENT_ID**`, `**GOOGLE_CLIENT_SECRET**`.
2. GCS: bucket + `**GCS_BUCKET_INGESTION**` + SA/ADC permissions.
3. DB: `**users**`, `**opportunities**`, `**opportunity_sources**` with `**source_type = 'drive'**`, owner = user who will OAuth.
4. User: `**GET /auth/google/url**` → sign in → `**POST /auth/google/callback**` → verify `**google_refresh_token**` in DB.
5. Drive: create folder with **name containing** `**oid`**, upload files.
6. Run `**POST /sync/trigger**` (manually or every 15 min).
7. Verify `**{OID}/raw/documents/**` in GCS, then processed/ingestion.

---

## Related code (for developers)


| Piece                                            | Location                             |
| ------------------------------------------------ | ------------------------------------ |
| Google authorize URL + scopes                    | `oauth_service.get_google_auth_url`  |
| Token exchange + `google_refresh_token`          | `oauth_service.exchange_google_code` |
| Drive folder search + recursive list + GCS write | `drive_plugin.sync_drive_source`     |
| Sync orchestration                               | `sync_routes.run_sync_job`           |


