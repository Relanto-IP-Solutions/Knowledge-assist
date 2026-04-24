import { api } from './apiClient'

const NAME_VALID_RE = /^[A-Za-z0-9 -]+$/

function extractDetail(e) {
  return e?.response?.data?.detail || e?.message || 'Something went wrong.'
}

function apiError(e) {
  const err = new Error(extractDetail(e))
  err.status = e?.response?.status
  return err
}

/** Fetch all opportunity requests (admin only). */
export async function listOpportunityRequests({ status, limit = 200 } = {}) {
  const params = { limit }
  if (status) params.status = status
  const { data } = await api.get('/opportunities/requests', { params })
  return data.requests ?? []
}

/**
 * Check if an opportunity name is already taken.
 * GET /opportunities/name-exists?name=<value>
 */
export async function checkNameExists(name) {
  try {
    const { data } = await api.get('/opportunities/name-exists', { params: { name } })
    console.log(data);
    return Boolean(data.exists)
  } catch (e) {
    throw apiError(e)
  }
}

/**
 * Submit an opportunity creation request (creates PENDING entry).
 * POST /opportunities/create
 * Returns { request_id, user_id, opportunity_title, submitted_at, status }
 */
export async function createOpportunityRequest(name) {
  const trimmed = String(name ?? '').trim()
  if (!trimmed) throw Object.assign(new Error('name is required.'), { status: 400 })
  if (!NAME_VALID_RE.test(trimmed)) {
    throw Object.assign(
      new Error('Only uppercase, lowercase, hyphen, and space are allowed.'),
      { status: 400 },
    )
  }
  try {
    const { data } = await api.post('/opportunities/create', { name: trimmed })
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/**
 * Approve or reject an opportunity request (admin only).
 * POST /opportunities/requests
 */
export async function reviewOpportunityRequest({ request_id, status, admin_remarks }) {
  try {
    const { data } = await api.post('/opportunities/requests', {
      request_id,
      status,
      admin_remarks: admin_remarks ?? null,
    })
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/** Fetch the current user's own opportunity requests. */
export async function getMyRequests() {
  try {
    const { data } = await api.get('/opportunities/my-requests')
    return data.requests ?? []
  } catch (e) {
    throw apiError(e)
  }
}

/**
 * Open an SSE stream for real-time notifications.
 * User identity is resolved server-side from the token.
 * Returns an EventSource instance — caller must call .close() on cleanup.
 */
export function openNotificationStream(token, { onMessage, onError } = {}) {
  const RAW_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  const base = import.meta.env.DEV ? window.location.origin : String(RAW_BASE).replace(/\/$/, '')
  const url = `${base}/opportunities/stream?token=${encodeURIComponent(token)}`
  const es = new EventSource(url)
  if (onMessage) {
    es.addEventListener('request_created', onMessage)
    es.addEventListener('request_approved', onMessage)
    es.addEventListener('request_rejected', onMessage)
  }
  if (onError) es.onerror = onError
  return es
}
