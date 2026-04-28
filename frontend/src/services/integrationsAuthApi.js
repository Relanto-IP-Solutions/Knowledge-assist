/**
 * OAuth URL helpers for connecting data sources (see project reference / Postman).
 * Reference: GET /auth/google/url, GET /auth/slack/url (+ user_email); Zoom often auto-linked — optional /auth/zoom/url.
 */

import { api, API_BASE } from './apiClient'
import { traced } from './connectorTrace'

/** Full backend URL for OAuth redirect URIs (always needs real host, not proxy). */
const BACKEND_BASE = String(import.meta.env.VITE_API_BASE || 'http://localhost:8000').replace(/\/$/, '')
/** Canonical frontend origin used for OAuth return URLs across all connectors. */
const FRONTEND_BASE = (() => {
  const explicit = import.meta.env.VITE_FRONTEND_APP_URL
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).trim().replace(/\/$/, '')
  }
  if (typeof window !== 'undefined') {
    return String(window.location.origin || '').replace(/\/$/, '')
  }
  return ''
})()

/** Set before redirecting to provider; App reads this to reopen the create-opportunity screen (no query on redirect_uri). */
export const OAUTH_RETURN_CREATE_OPP_KEY = 'pzf_after_oauth_page'
/** sessionStorage keys used to restore context after OAuth redirect */
export const OAUTH_OPP_ID_KEY       = 'pzf_oauth_opp_id'
export const OAUTH_OPP_NAME_KEY     = 'pzf_oauth_opp_name'
export const OAUTH_PROVIDER_KEY     = 'pzf_oauth_provider'
/** Per-opportunity connected sources: JSON array stored at `pzf_src_connected_{oppId}` */
export function connectedSourcesKey(oppId) { return `pzf_src_connected_${oppId}` }

/**
 * Redirect URI sent to `/auth/google/url` (and similar). Google requires an **exact** match with
 * "Authorized redirect URIs" in Google Cloud Console — including trailing slash and **no extra query**.
 *
 * - Set `VITE_OAUTH_REDIRECT_URI` in `.env` to the exact URL you registered (e.g. `http://localhost:5173/`).
 * - Default: `{origin}/` (trailing slash). Use the same host you open in the browser (`localhost` vs `127.0.0.1` are different).
 */
export function getOAuthRedirectUri() {
  const explicit = import.meta.env.VITE_OAUTH_REDIRECT_URI
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).trim()
  }
  return `${FRONTEND_BASE}/`
}

/**
 * The `redirect_uri` sent to Gmail OAuth endpoints — this is the **backend's own callback**,
 * NOT the frontend URL. Google must have this URL registered in the Cloud Console.
 * Set `VITE_GMAIL_REDIRECT_URI` in `.env` to override.
 * Defaults to `{VITE_API_BASE}/integrations/gmail/callback`.
 */
export function getGmailBackendRedirectUri() {
  const explicit = import.meta.env.VITE_GMAIL_REDIRECT_URI
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).trim()
  }
  return `${BACKEND_BASE}/integrations/gmail/callback`
}

/**
 * `redirect_uri` for GET /integrations/drive/authorize-info/{oid} — backend Google OAuth callback.
 * Override with `VITE_DRIVE_GOOGLE_REDIRECT_URI`. Defaults to `{VITE_API_BASE}/auth/google/callback`.
 */
export function getDriveOAuthRedirectUri() {
  const explicit = import.meta.env.VITE_DRIVE_GOOGLE_REDIRECT_URI
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).trim()
  }
  return `${BACKEND_BASE}/auth/google/callback`
}

/**
 * return_url for workspace-level Gmail discover OAuth — user lands at /gmail-result.
 * Override with `VITE_GMAIL_FRONTEND_REDIRECT_URI` if needed.
 */
export function getGmailFrontendResultUrl() {
  const explicit = import.meta.env.VITE_GMAIL_FRONTEND_REDIRECT_URI
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).trim()
  }
  return `${FRONTEND_BASE}/gmail-result`
}

/**
 * return_url for per-opportunity Gmail connect OAuth — user lands at /sources/:oid.
 */
export function getGmailSourcesReturnUrl(oid) {
  return `${FRONTEND_BASE}/sources/${oid}`
}

/**
 * return_url for per-opportunity Drive connect OAuth — user lands at /sources/:oid.
 */
export function getDriveSourcesReturnUrl(oid) {
  return `${FRONTEND_BASE}/sources/${oid}`
}

/**
 * @param {string} path - e.g. '/auth/google/url'
 * @param {Record<string, string>} [query]
 * @returns {Promise<{ auth_url: string }>}
 */
async function fetchAuthUrlJson(path, query = {}) {
  const { data } = await api.get(path, { params: query })
  const authUrl = data.auth_url ?? data.url ?? data.authorization_url
  if (!authUrl || typeof authUrl !== 'string') {
    throw new Error('Response missing auth_url')
  }
  return { auth_url: authUrl }
}

/** @param {string} redirectUri - absolute URL OAuth provider will redirect to */
export async function getGoogleOAuthUrl(redirectUri) {
  return fetchAuthUrlJson('/auth/google/url', {
    redirect_uri: redirectUri,
  })
}

/**
 * GET /auth/google/url?provider=drive&user_email=&redirect_uri=
 * Returns { auth_url, already_connected }.
 * If already_connected is true or auth_url is null, skip OAuth and connect directly.
 */
export async function getDriveAuthUrl(userEmail, oid, redirectUri) {
  const { data } = await api.get('/auth/google/url', {
    params: { provider: 'drive', user_email: userEmail, oid, redirect_uri: redirectUri },
  })
  return data
}

/**
 * Gmail OAuth URL — backend uses the same Google OAuth endpoint.
 * @param {string} redirectUri
 */
export async function getGmailOAuthUrl(redirectUri) {
  return fetchAuthUrlJson('/auth/google/url', {
    redirect_uri: redirectUri,
  })
}

/**
 * GET /auth/google/url?provider=gmail&oid=&redirect_uri=
 *
 * Used by the per-opportunity Gmail re-auth path on Sources when the stored
 * refresh token is revoked. Mirrors {@link getDriveAuthUrl} so the OAuth
 * flow targets the **generic** backend callback (`/auth/google/callback`)
 * which doesn't require an HMAC-signed gmail-specific state — the simple
 * `provider:oid` state from this endpoint is what that callback validates.
 * After exchange, the backend redirects to `/projects/<oid>?provider=gmail`
 * which the frontend forwards to `/sources/<oid>`.
 *
 * @param {string} oid
 * @param {string} redirectUri — should be {VITE_API_BASE}/auth/google/callback
 * @returns {Promise<{ auth_url: string | null, already_connected?: boolean }>}
 */
export async function getGmailReauthAuthUrl(oid, redirectUri) {
  const { data } = await api.get('/auth/google/url', {
    params: { provider: 'gmail', oid, redirect_uri: redirectUri },
  })
  return data
}

/**
 * POST /auth/google/callback
 * Exchanges the OAuth code returned by Google for backend tokens.
 * @param {string} code - from ?code= query param after redirect
 * @param {string} redirectUri - must match what was sent to /auth/google/url
 * @param {string} userEmail
 */
export async function exchangeGoogleOAuthCallback(code, redirectUri, userEmail) {
  const { data } = await api.post('/auth/google/callback', {
    code,
    redirect_uri: redirectUri,
    user_email: userEmail,
  })
  return data
}

/**
 * POST /gmail/discover
 * Scans the authenticated Gmail account for relevant threads.
 * @param {string} userEmail
 */
export async function discoverGmail(userEmail) {
  const { data } = await api.post('/gmail/discover', { user_email: userEmail })
  return data
}

/**
 * POST /integrations/gmail/discover
 * Backend decides whether to discover immediately or return an OAuth URL.
 * @param {{ redirect_uri: string, return_url?: string, oid?: string, user_email?: string }} payload
 * Response:
 *   { requires_oauth: false, message, discovery_result: { threads_scanned, threads_with_oid, opportunities_created, ... } }
 *   { requires_oauth: true, auth_url, message }
 */
export async function startGmailDiscover(payload) {
  const { data } = await api.post('/integrations/gmail/discover', payload || {})
  return data
}

/**
 * Sources page (per opportunity id `oid`): after the user enters a Gmail address,
 * run **discover → connect → metrics** using the same `oid` and `user_email` everywhere.
 *
 * @param {string} oid — backend opportunity id (use {@link toApiOpportunityId} from config if UI id differs)
 * @param {string} userEmail
 * @returns {Promise<
 *   | { step: 'oauth_after_discover', auth_url: string, discoverResult: object }
 *   | { step: 'oauth_after_connect', auth_url: string, discoverResult: object, connectResult: object }
 *   | { step: 'complete', discoverResult: object, connectResult: object, metrics: object | null }
 * >}
 */
export async function runGmailOpportunityConnectSequence(oid, userEmail) {
  const email = String(userEmail || '').trim().toLowerCase()
  if (!email) throw new Error('Gmail address is required')

  const oidStr = String(oid ?? '').trim()
  if (!oidStr) throw new Error('Opportunity id is required')

  const redirectUri = getGmailBackendRedirectUri()
  // Per-opportunity Gmail flows should always return to the current Sources page.
  const discoverReturnUrl = getGmailSourcesReturnUrl(oidStr)
  const connectReturnUrl = getGmailSourcesReturnUrl(oidStr)

  const discoverResult = await startGmailDiscover({
    redirect_uri: redirectUri,
    return_url: discoverReturnUrl,
    oid: oidStr,
    user_email: email,
  })

  if (discoverResult?.requires_oauth && discoverResult?.auth_url) {
    return {
      step: 'oauth_after_discover',
      auth_url: discoverResult.auth_url,
      discoverResult,
    }
  }

  const connectResult = await connectGmail(oidStr, redirectUri, email, connectReturnUrl)

  if (connectResult?.requires_oauth && connectResult?.auth_url) {
    return {
      step: 'oauth_after_connect',
      auth_url: connectResult.auth_url,
      discoverResult,
      connectResult,
    }
  }

  const okConnect = connectResult?.requires_oauth === false || connectResult?.status === 'ACTIVE'
  if (!okConnect) {
    const err = new Error('Unexpected response from Gmail connect')
    err.detail = connectResult
    throw err
  }

  let metrics = null
  try {
    metrics = await fetchGmailMetrics(oidStr, email)
  } catch {
    metrics = null
  }

  return {
    step: 'complete',
    discoverResult,
    connectResult,
    metrics,
  }
}

/** @param {string} userEmail - required by reference */
export async function getSlackOAuthUrl(redirectUri, userEmail) {
  return fetchAuthUrlJson('/auth/slack/url', {
    redirect_uri: redirectUri,
    user_email: userEmail,
  })
}

/** Optional; reference notes Zoom may be automatic — backend may still expose this. */
export async function getZoomOAuthUrl(redirectUri) {
  return fetchAuthUrlJson('/auth/zoom/url', {
    redirect_uri: redirectUri,
  })
}

// ── Drive connector API (authorize-info → connect → metrics) ───────────────

/** POST /integrations/drive/connect/{oid} may run discovery + ingestion (10s+). */
export const DRIVE_CONNECT_TIMEOUT_MS = (() => {
  const n = Number(import.meta.env.VITE_DRIVE_CONNECT_TIMEOUT_MS)
  return Number.isFinite(n) && n >= 5_000 ? Math.floor(n) : 60_000
})()

const _driveInfoCache    = new Map()
const _driveMetricsCache = new Map()

function _driveSsKey(type, oid) { return `pzf_drive_${type}_${oid}` }

function _getDriveStorage() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) return window.localStorage
  } catch { /**/ }
  return null
}

function _writeDriveStorage(type, oid, data) {
  const storage = _getDriveStorage()
  if (storage) {
    try { storage.setItem(_driveSsKey(type, oid), JSON.stringify(data)) } catch { /**/ }
  }
  try { sessionStorage.setItem(_driveSsKey(type, oid), JSON.stringify(data)) } catch { /**/ }
}

function _readDriveStorage(type, oid) {
  const storage = _getDriveStorage()
  if (storage) {
    try {
      const raw = storage.getItem(_driveSsKey(type, oid))
      if (raw) return JSON.parse(raw)
    } catch { /**/ }
  }
  try {
    const raw = sessionStorage.getItem(_driveSsKey(type, oid))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Synchronous read — checks memory then sessionStorage. */
export function getCachedDriveConnectInfo(oid) {
  if (!_driveInfoCache.has(oid)) {
    const stored = _readDriveStorage('info', oid)
    if (stored) _driveInfoCache.set(oid, stored)
  }
  return _driveInfoCache.get(oid) ?? null
}

/** Synchronous read — checks memory then sessionStorage. */
export function getCachedDriveMetrics(oid) {
  if (!_driveMetricsCache.has(oid)) {
    const stored = _readDriveStorage('metrics', oid)
    if (stored) _driveMetricsCache.set(oid, stored)
  }
  return _driveMetricsCache.get(oid) ?? null
}

/**
 * GET /integrations/drive/authorize-info/{oid}
 * Query: user_email, redirect_uri (backend Google OAuth callback).
 * @param {string} oid
 * @param {{ userEmail?: string, redirectUri?: string, returnUrl?: string }} [options]
 */
export async function fetchDriveConnectInfo(oid, options = {}) {
  return traced('fetchDriveConnectInfo', async () => {
    const userEmail = options.userEmail != null ? String(options.userEmail).trim().toLowerCase() : ''
    const redirectUri = options.redirectUri != null && String(options.redirectUri).trim() !== ''
      ? String(options.redirectUri).trim()
      : getDriveOAuthRedirectUri()
    const params = { redirect_uri: redirectUri }
    if (userEmail) params.user_email = userEmail
    if (options.returnUrl && String(options.returnUrl).trim()) params.return_url = String(options.returnUrl).trim()

    const write = (data) => {
      _driveInfoCache.set(oid, data)
      _writeDriveStorage('info', oid, data)
      return data
    }

    try {
      const { data } = await api.get(`/integrations/drive/authorize-info/${encodeURIComponent(oid)}`, { params })
      return write(data)
    } catch (e) {
      if (e?.response?.status === 404) {
        const { data } = await api.get(`/authorize-info/drive/${encodeURIComponent(oid)}`)
        return write(data)
      }
      throw e
    }
  })
}

/**
 * GET /integrations/drive/metrics/{oid} (optional ?user_email=)
 * Falls back to GET /metrics/drive/{oid}.
 * @param {string} oid
 * @param {string} [userEmail]
 * @param {{ signal?: AbortSignal }} [options] — pass an AbortSignal to cancel slow/hanging requests.
 */
export async function fetchDriveMetrics(oid, userEmail, options = {}) {
  return traced('fetchDriveMetrics', async () => {
    const params = {}
    if (userEmail && String(userEmail).trim()) {
      params.user_email = String(userEmail).trim()
    }
    const opts = {
      params: Object.keys(params).length ? params : undefined,
      ...(options.signal ? { signal: options.signal } : {}),
    }
    let data
    try {
      ;({ data } = await api.get(`/integrations/drive/metrics/${encodeURIComponent(oid)}`, opts))
    } catch (e) {
      if (e?.response?.status === 404) {
        ;({ data } = await api.get(`/metrics/drive/${encodeURIComponent(oid)}`, opts))
      } else {
        throw e
      }
    }
    _driveMetricsCache.set(oid, data)
    _writeDriveStorage('metrics', oid, data)
    return data
  })
}

/**
 * POST /authorize/drive/{oid}
 * Activates Drive for the opportunity when connector auth is already present.
 */
export async function authorizeDrive(oid) {
  return traced('authorizeDrive', async () => {
    const { data } = await api.post(`/authorize/drive/${encodeURIComponent(oid)}`, {})
    const existing = getCachedDriveConnectInfo(oid) ?? {}
    const updated = { ...existing, ...data, status: data?.status ?? 'ACTIVE' }
    _driveInfoCache.set(oid, updated)
    _writeDriveStorage('info', oid, updated)
    return data
  })
}

/**
 * POST /drive/discover
 * Discovers OID folders from Drive root and creates opportunity/source mappings.
 */
export async function discoverDrive() {
  return traced('discoverDrive', async () => {
    const { data } = await api.post('/drive/discover', {})
    return data
  })
}

/**
 * POST /integrations/drive/connect/{oid}?user_email=
 * Synchronous discovery + ingestion for user-scoped Drive.
 * @param {string} oid
 * @param {string} userEmail
 */
export async function connectDrive(oid, userEmail) {
  return traced('connectDrive', async () => {
    const email = String(userEmail ?? '').trim().toLowerCase()
    if (!email) throw new Error('Google account email is required for Drive connect')

    const params = { user_email: email }
    try {
      const { data } = await api.post(
        `/integrations/drive/connect/${encodeURIComponent(oid)}`,
        {},
        { params, timeout: DRIVE_CONNECT_TIMEOUT_MS },
      )
      const existing = getCachedDriveConnectInfo(oid) ?? {}
      const updated = { ...existing, ...data, status: data?.status ?? 'ACTIVE' }
      _driveInfoCache.set(oid, updated)
      _writeDriveStorage('info', oid, updated)
      if (data && typeof data === 'object') {
        _driveMetricsCache.set(oid, data)
        _writeDriveStorage('metrics', oid, data)
      }
      return data
    } catch (e) {
      const status = e?.response?.status
      if (status === 404 || status === 405) {
        return authorizeDrive(oid)
      }
      throw e
    }
  })
}

// ── Gmail integration (per-opportunity, mirrors Zoom/Slack pattern) ─────────

const _gmailInfoCache    = new Map()
const _gmailMetricsCache = new Map()

function _gmailSsKey(type, oid) { return `pzf_gmail_${type}_${oid}` }

function _gmailMetricsCacheKey(oid, userEmail) {
  const e = (userEmail && String(userEmail).trim().toLowerCase()) || ''
  return `${encodeURIComponent(oid)}::${e}`
}

function _gmailMetricsSsKey(oid, userEmail) {
  const e = (userEmail && String(userEmail).trim().toLowerCase()) || '_'
  return `pzf_gmail_metrics_${oid}_${e}`
}

function _writeGmailStorage(type, oid, data) {
  try { sessionStorage.setItem(_gmailSsKey(type, oid), JSON.stringify(data)) } catch { /**/ }
}

function _writeGmailMetricsStorage(oid, userEmail, data) {
  try { sessionStorage.setItem(_gmailMetricsSsKey(oid, userEmail), JSON.stringify(data)) } catch { /**/ }
}

function _readGmailStorage(type, oid) {
  try {
    const raw = sessionStorage.getItem(_gmailSsKey(type, oid))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function _readGmailMetricsStorage(oid, userEmail) {
  try {
    const raw = sessionStorage.getItem(_gmailMetricsSsKey(oid, userEmail))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Synchronous read — checks memory then sessionStorage. Returns null if never fetched. */
export function getCachedGmailConnectInfo(oid) {
  if (!_gmailInfoCache.has(oid)) {
    const stored = _readGmailStorage('info', oid)
    if (stored) _gmailInfoCache.set(oid, stored)
  }
  return _gmailInfoCache.get(oid) ?? null
}

/**
 * Write connect info into memory + sessionStorage caches.
 * @param {string} oid
 * @param {object} data
 */
export function setCachedGmailConnectInfo(oid, data) {
  _gmailInfoCache.set(oid, data)
  _writeGmailStorage('info', oid, data)
}

/**
 * Synchronous read — checks memory then sessionStorage. Returns null if never fetched.
 * @param {string} oid
 * @param {string} [userEmail] — optional; must match fetchGmailMetrics call for cache hit
 */
export function getCachedGmailMetrics(oid, userEmail) {
  const mk = _gmailMetricsCacheKey(oid, userEmail)
  if (!_gmailMetricsCache.has(mk)) {
    const stored = _readGmailMetricsStorage(oid, userEmail)
    if (stored) _gmailMetricsCache.set(mk, stored)
  }
  return _gmailMetricsCache.get(mk) ?? null
}

/**
 * Write metrics into memory + sessionStorage caches.
 * @param {string} oid
 * @param {string|undefined} userEmail
 * @param {object} data
 */
export function setCachedGmailMetrics(oid, userEmail, data) {
  const mk = _gmailMetricsCacheKey(oid, userEmail)
  _gmailMetricsCache.set(mk, data)
  _writeGmailMetricsStorage(oid, userEmail, data)
}

/**
 * GET /integrations/gmail/connect-info/{oid}
 * Returns { status: 'UNAUTHORIZED' | 'DISCOVERED' | 'ACTIVE', requires_oauth: bool }
 */
export async function fetchGmailConnectInfo(oid) {
  const { data } = await api.get(`/integrations/gmail/connect-info/${encodeURIComponent(oid)}`)
  _gmailInfoCache.set(oid, data)
  _writeGmailStorage('info', oid, data)
  return data
}

/**
 * POST /integrations/gmail/connect/{oid}
 * Starts per-opportunity Gmail sync.
 * Body: { redirect_uri, user_email }  (matches Postman)
 * Returns { requires_oauth: false } or { requires_oauth: true, auth_url }.
 */
export async function connectGmail(oid, redirectUri, userEmail, returnUrl) {
  const body = {
    redirect_uri: redirectUri ?? getGmailFrontendResultUrl(),
    user_email: userEmail,
  }
  if (returnUrl && String(returnUrl).trim()) {
    body.return_url = String(returnUrl).trim()
  }
  const { data } = await api.post(`/integrations/gmail/connect/${encodeURIComponent(oid)}`, body)
  if (!data.requires_oauth) {
    const existing = getCachedGmailConnectInfo(oid) ?? {}
    const updated  = { ...existing, status: 'ACTIVE', requires_oauth: false }
    _gmailInfoCache.set(oid, updated)
    _writeGmailStorage('info', oid, updated)
  }
  return data
}

/**
 * GET /integrations/gmail/callback?code=...&state=...
 * Called by the frontend after Google redirects back with ?code and signed ?state.
 * Backend exchanges the code, activates the source, returns { status: 'ACTIVE', oid }.
 */
export async function callGmailOAuthCallback(code, state) {
  const { data } = await api.get('/integrations/gmail/callback', { params: { code, state } })
  return data
}

/**
 * POST /integrations/gmail/authorize/{oid}
 * Activates Gmail for this opportunity when Google scope is already present (status = DISCOVERED).
 */
export async function authorizeGmail(oid) {
  const { data } = await api.post(`/integrations/gmail/authorize/${encodeURIComponent(oid)}`, {})
  const existing = getCachedGmailConnectInfo(oid) ?? {}
  const updated  = { ...existing, status: 'ACTIVE', requires_oauth: false }
  _gmailInfoCache.set(oid, updated)
  _writeGmailStorage('info', oid, updated)
  return data
}

/**
 * GET /metrics/gmail/{oid} — read-only metrics (poll after connect).
 * Falls back to GET /integrations/gmail/metrics/{oid} if the new route is missing (404).
 * Optional: ?user_email=... for mailbox-scoped breakdown.
 * @param {string} oid
 * @param {string} [userEmail]
 */
export async function fetchGmailMetrics(oid, userEmail) {
  const params = {}
  if (userEmail && String(userEmail).trim()) {
    params.user_email = String(userEmail).trim()
  }
  const opts = { params: Object.keys(params).length ? params : undefined }
  let data
  try {
    ;({ data } = await api.get(`/metrics/gmail/${encodeURIComponent(oid)}`, opts))
  } catch (e) {
    if (e?.response?.status === 404) {
      ;({ data } = await api.get(`/integrations/gmail/metrics/${encodeURIComponent(oid)}`, opts))
    } else {
      throw e
    }
  }
  const mk = _gmailMetricsCacheKey(oid, userEmail)
  _gmailMetricsCache.set(mk, data)
  _writeGmailMetricsStorage(oid, userEmail, data)
  return data
}

// ── Opportunity source registration (Postman: opportunities/gmail, opportunities/slack) ──

/**
 * POST /opportunities/gmail
 * Ensures an opportunity row + gmail source row exist.
 * Call before Google/Gmail OAuth redirect.
 * @param {string} opportunityId
 * @param {string} name - display name of the opportunity
 * @param {string} ownerEmail - user's email
 */
export async function ensureGmailSource(opportunityId, name, ownerEmail) {
  const { data } = await api.post('/opportunities/gmail', {
    opportunity_id: opportunityId,
    name: name || opportunityId,
    owner_email: ownerEmail,
  })
  return data
}

/**
 * POST /opportunities/slack
 * Ensures an opportunity row + slack source row exist.
 * Call before Slack OAuth redirect.
 * @param {string} opportunityId
 * @param {string} name - display name of the opportunity
 * @param {string} ownerEmail - user's email
 */
export async function ensureSlackSource(opportunityId, name, ownerEmail) {
  const { data } = await api.post('/opportunities/slack', {
    opportunity_id: opportunityId,
    name: name || opportunityId,
    owner_email: ownerEmail,
  })
  return data
}

// ── Zoom connector API (professional ingestion: discover → connect → metrics) ─

/** Default `days_lookback` for POST /zoom/discover (backend default 14). Override with VITE_ZOOM_DAYS_LOOKBACK. */
export const ZOOM_DISCOVER_DEFAULT_DAYS = (() => {
  const n = Number(import.meta.env.VITE_ZOOM_DAYS_LOOKBACK)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 14
})()
/** POST /integrations/zoom/connect can take 10–20s+ (org-wide scan); guide recommends ~60s client timeout */
export const ZOOM_CONNECT_TIMEOUT_MS = 60_000

/**
 * Zoom state is persisted to sessionStorage so it survives HMR and component
 * re-mounts. Memory Maps are populated lazily from sessionStorage on first read.
 */
const _zoomInfoCache    = new Map()
const _zoomMetricsCache = new Map()

function _ssKey(type, oid) { return `pzf_zoom_${type}_${oid}` }

function _writeStorage(type, oid, data) {
  try { sessionStorage.setItem(_ssKey(type, oid), JSON.stringify(data)) } catch { /**/ }
}

function _readStorage(type, oid) {
  try {
    const raw = sessionStorage.getItem(_ssKey(type, oid))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Synchronous read — checks memory then sessionStorage. Returns null if never fetched. */
export function getCachedZoomConnectInfo(oid) {
  if (!_zoomInfoCache.has(oid)) {
    const stored = _readStorage('info', oid)
    if (stored) _zoomInfoCache.set(oid, stored)
  }
  return _zoomInfoCache.get(oid) ?? null
}

/** Synchronous read — checks memory then sessionStorage. Returns null if never fetched. */
export function getCachedZoomMetrics(oid) {
  if (!_zoomMetricsCache.has(oid)) {
    const stored = _readStorage('metrics', oid)
    if (stored) _zoomMetricsCache.set(oid, stored)
  }
  return _zoomMetricsCache.get(oid) ?? null
}

/**
 * GET /integrations/zoom/connect-info/{oid}
 * Result is written to both memory and sessionStorage for instant re-mount reads.
 */
export async function fetchZoomConnectInfo(oid) {
  const { data } = await api.get(`/integrations/zoom/connect-info/${encodeURIComponent(oid)}`)
  _zoomInfoCache.set(oid, data)
  _writeStorage('info', oid, data)
  return data
}

/**
 * POST /integrations/zoom/authorize/{oid}
 * Legacy activate toggle — prefer {@link connectZoom} for ingestion.
 */
export async function authorizeZoom(oid, active = true) {
  const { data } = await api.post(`/integrations/zoom/authorize/${encodeURIComponent(oid)}`, { active })
  const newStatus = active ? 'ACTIVE' : 'DISCOVERED'
  const existing = getCachedZoomConnectInfo(oid) ?? {}
  const updated  = { ...existing, status: newStatus }
  _zoomInfoCache.set(oid, updated)
  _writeStorage('info', oid, updated)
  return data
}

/**
 * POST /zoom/discover?oid=&days_lookback=
 * Organization-wide scan for meetings matching this project (no download).
 */
export async function discoverZoom(oid, daysLookback = ZOOM_DISCOVER_DEFAULT_DAYS) {
  const { data } = await api.post('/zoom/discover', {}, {
    params: {
      oid: String(oid ?? '').trim(),
      days_lookback: Number(daysLookback) > 0 ? Number(daysLookback) : ZOOM_DISCOVER_DEFAULT_DAYS,
    },
  })
  return data
}

/**
 * POST /integrations/zoom/connect/{oid}
 * Synchronous ingestion to storage — allow long timeout (see {@link ZOOM_CONNECT_TIMEOUT_MS}).
 */
export async function connectZoom(oid) {
  const { data } = await api.post(
    `/integrations/zoom/connect/${encodeURIComponent(oid)}`,
    {},
    { timeout: ZOOM_CONNECT_TIMEOUT_MS },
  )
  const existing = getCachedZoomConnectInfo(oid) ?? {}
  const updated = {
    ...existing,
    ...data,
    status: data?.status ?? 'ACTIVE',
  }
  _zoomInfoCache.set(oid, updated)
  _writeStorage('info', oid, updated)
  if (data && typeof data === 'object') {
    _zoomMetricsCache.set(oid, data)
    _writeStorage('metrics', oid, data)
  }
  return data
}

/**
 * GET /integrations/zoom/metrics/{oid}
 * Lightweight dashboard read — no Zoom API credits.
 */
export async function fetchZoomMetrics(oid) {
  const { data } = await api.get(`/integrations/zoom/metrics/${encodeURIComponent(oid)}`)
  _zoomMetricsCache.set(oid, data)
  _writeStorage('metrics', oid, data)
  return data
}

// ── Slack connector API (professional ingestion: discover → connect → metrics) ─

/** POST /integrations/slack/connect/{oid} can take 10–15s+; match Zoom client timeout */
export const SLACK_CONNECT_TIMEOUT_MS = (() => {
  const n = Number(import.meta.env.VITE_SLACK_CONNECT_TIMEOUT_MS)
  return Number.isFinite(n) && n >= 5_000 ? Math.floor(n) : 60_000
})()

const _slackInfoCache    = new Map()
const _slackMetricsCache = new Map()

function _slackSsKey(type, oid) { return `pzf_slack_${type}_${oid}` }

function _writeSlackStorage(type, oid, data) {
  try { sessionStorage.setItem(_slackSsKey(type, oid), JSON.stringify(data)) } catch { /**/ }
}

function _readSlackStorage(type, oid) {
  try {
    const raw = sessionStorage.getItem(_slackSsKey(type, oid))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Synchronous read — checks memory then sessionStorage. */
export function getCachedSlackConnectInfo(oid) {
  if (!_slackInfoCache.has(oid)) {
    const stored = _readSlackStorage('info', oid)
    if (stored) _slackInfoCache.set(oid, stored)
  }
  return _slackInfoCache.get(oid) ?? null
}

/** Synchronous read — checks memory then sessionStorage. */
export function getCachedSlackMetrics(oid) {
  if (!_slackMetricsCache.has(oid)) {
    const stored = _readSlackStorage('metrics', oid)
    if (stored) _slackMetricsCache.set(oid, stored)
  }
  return _slackMetricsCache.get(oid) ?? null
}

/**
 * GET /integrations/slack/authorize-info/{oid}
 * Returns connection status for this opportunity's Slack source.
 */
export async function fetchSlackConnectInfo(oid) {
  const { data } = await api.get(`/integrations/slack/authorize-info/${encodeURIComponent(oid)}`)
  _slackInfoCache.set(oid, data)
  _writeSlackStorage('info', oid, data)
  return data
}

/**
 * POST /integrations/slack/authorize/{oid}
 * Activates Slack for this opportunity.
 */
export async function authorizeSlack(oid) {
  const { data } = await api.post(`/integrations/slack/authorize/${encodeURIComponent(oid)}`, {})
  const existing = getCachedSlackConnectInfo(oid) ?? {}
  const updated  = { ...existing, status: 'ACTIVE' }
  _slackInfoCache.set(oid, updated)
  _writeSlackStorage('info', oid, updated)
  return data
}

/**
 * GET /integrations/slack/metrics/{oid}
 * Returns message/channel counts and last sync time for this opportunity.
 */
export async function fetchSlackMetrics(oid) {
  const { data } = await api.get(`/integrations/slack/metrics/${encodeURIComponent(oid)}`)
  _slackMetricsCache.set(oid, data)
  _writeSlackStorage('metrics', oid, data)
  return data
}

/**
 * POST /integrations/slack/discover?oid=
 * Targeted channel discovery for one project (strict isolation); no message sync.
 * @param {string} oid - backend opportunity id
 */
export async function discoverSlackForProject(oid) {
  const oidStr = String(oid ?? '').trim()
  if (!oidStr) throw new Error('Opportunity id is required')
  const { data } = await api.post('/integrations/slack/discover', {}, { params: { oid: oidStr } })
  return data
}

/**
 * POST /integrations/slack/connect/{oid}
 * Synchronous discovery, activation, and history download for this project.
 */
export async function connectSlack(oid) {
  const oidStr = String(oid ?? '').trim()
  if (!oidStr) throw new Error('Opportunity id is required')
  const { data } = await api.post(
    `/integrations/slack/connect/${encodeURIComponent(oidStr)}`,
    {},
    { timeout: SLACK_CONNECT_TIMEOUT_MS },
  )
  const existing = getCachedSlackConnectInfo(oidStr) ?? {}
  const updated = {
    ...existing,
    ...data,
    status: data?.status ?? 'ACTIVE',
  }
  _slackInfoCache.set(oidStr, updated)
  _writeSlackStorage('info', oidStr, updated)
  if (data && typeof data === 'object') {
    _slackMetricsCache.set(oidStr, data)
    _writeSlackStorage('metrics', oidStr, data)
  }
  return data
}

/**
 * POST /integrations/slack/discover (body: redirect_uri)
 * Workspace-wide scan after OAuth — used by App redirect flow, not per-opportunity Sources card.
 * @param {string} redirectUri
 */
export async function discoverSlack(redirectUri) {
  const { data } = await api.post('/integrations/slack/discover', { redirect_uri: redirectUri })
  return data
}

/**
 * POST /auth/slack/callback
 * Exchanges the Slack OAuth code for backend tokens.
 * @param {string} code
 * @param {string} redirectUri
 * @param {string} userEmail
 */
export async function exchangeSlackOAuthCallback(code, redirectUri, userEmail) {
  const { data } = await api.post('/auth/slack/callback', {
    code,
    redirect_uri: redirectUri,
    user_email: userEmail,
  })
  return data
}

// ── OneDrive connector API ───────────────────────────────────────────

/**
 * `redirect_uri` for GET /auth/microsoft/url — backend Microsoft OAuth callback.
 * Override with `VITE_ONEDRIVE_REDIRECT_URI`. Defaults to `{VITE_API_BASE}/oauth/microsoft/callback`.
 */
export function getOneDriveOAuthRedirectUri() {
  const explicit = import.meta.env.VITE_ONEDRIVE_REDIRECT_URI
  if (explicit != null && String(explicit).trim() !== '') return String(explicit).trim()
  return `${BACKEND_BASE}/oauth/microsoft/callback`
}

const _oneDriveMetricsCache = new Map()

function _oneDriveSsKey(oid) { return `pzf_onedrive_metrics_${oid}` }

function _getOneDriveStorage() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) return window.localStorage
  } catch { /**/ }
  return null
}

/** Dual-write so the previous "Active" status survives hard reloads (localStorage) while still
 * working in private windows where localStorage may be limited (sessionStorage). */
function _writeOneDriveStorage(oid, data) {
  const storage = _getOneDriveStorage()
  if (storage) {
    try { storage.setItem(_oneDriveSsKey(oid), JSON.stringify(data)) } catch { /**/ }
  }
  try { sessionStorage.setItem(_oneDriveSsKey(oid), JSON.stringify(data)) } catch { /**/ }
}

function _readOneDriveStorage(oid) {
  const storage = _getOneDriveStorage()
  if (storage) {
    try {
      const raw = storage.getItem(_oneDriveSsKey(oid))
      if (raw) return JSON.parse(raw)
    } catch { /**/ }
  }
  try {
    const raw = sessionStorage.getItem(_oneDriveSsKey(oid))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function getCachedOneDriveMetrics(oid) {
  if (!_oneDriveMetricsCache.has(oid)) {
    const stored = _readOneDriveStorage(oid)
    if (stored) _oneDriveMetricsCache.set(oid, stored)
  }
  return _oneDriveMetricsCache.get(oid) ?? null
}

/**
 * GET /auth/microsoft/url?redirect_uri=&user_email=&oid=
 * Returns { auth_url } if OAuth is needed, or null auth_url if user is already connected.
 */
export async function getMicrosoftOAuthUrl(redirectUri, userEmail, oid) {
  const { data } = await api.get('/auth/microsoft/url', {
    params: { redirect_uri: redirectUri, user_email: userEmail, oid },
  })
  return data
}

/**
 * POST /integrations/onedrive/connect/{oid}?user_email=
 * Syncs OneDrive files for this opportunity.
 */
export async function connectOneDrive(oid, userEmail) {
  const oidStr = String(oid ?? '').trim()
  if (!oidStr) throw new Error('Opportunity id is required')
  const { data } = await api.post(
    `/integrations/onedrive/connect/${encodeURIComponent(oidStr)}`,
    {},
    { params: { user_email: userEmail } },
  )
  // Only cache when the response carries the metrics shape (total_files /
  // last_synced_at). The OneDrive connect endpoint returns a thin status
  // payload ({status, folder_id, sync_started}) — caching that would
  // overwrite the real metrics cache with 0-file stubs and force users to
  // hit Resync to recover. The follow-up fetchOneDriveMetrics call inside
  // runConnectAndMetrics will populate the cache with real values.
  if (
    data
    && typeof data === 'object'
    && (Object.prototype.hasOwnProperty.call(data, 'total_files')
      || Object.prototype.hasOwnProperty.call(data, 'last_synced_at'))
  ) {
    _oneDriveMetricsCache.set(oidStr, data)
    _writeOneDriveStorage(oidStr, data)
  }
  return data
}

/**
 * GET /integrations/onedrive/authorize-info/{oid}?user_email=
 * Returns { has_onedrive_connection: bool, ... } for pre-sync status check.
 */
export async function getOneDriveAuthorizeInfo(oid, userEmail) {
  const { data } = await api.get(`/integrations/onedrive/authorize-info/${encodeURIComponent(oid)}`, {
    params: { user_email: userEmail },
  })
  return data
}

/**
 * GET /integrations/onedrive/metrics/{oid}
 * Returns OneDrive ingestion metrics for one opportunity.
 * @param {string} oid
 * @param {{ signal?: AbortSignal }} [options] — pass an AbortSignal to cancel slow/hanging requests.
 */
export async function fetchOneDriveMetrics(oid, options = {}) {
  const opts = options.signal ? { signal: options.signal } : undefined
  const { data } = await api.get(`/integrations/onedrive/metrics/${encodeURIComponent(oid)}`, opts)
  _oneDriveMetricsCache.set(oid, data)
  _writeOneDriveStorage(oid, data)
  return data
}

/**
 * POST /integrations/slack/orchestrate/{oid}
 * Creates a Slack channel and invites the specified team members.
 * @param {string} oid
 * @param {string} customChannelName
 * @param {string[]} teamEmails
 */
export async function orchestrateSlack(oid, customChannelName, teamEmails) {
  const oidStr = String(oid ?? '').trim()
  if (!oidStr) throw new Error('Opportunity id is required')
  const { data } = await api.post(`/integrations/slack/orchestrate/${encodeURIComponent(oidStr)}`, {
    custom_channel_name: customChannelName,
    team_emails: teamEmails,
  })
  return data
}
