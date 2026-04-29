import { API_BASE } from './apiClient'
import { getAuthTokenForRequest } from './authToken'

export const NOTIF_DIGEST_CURSOR_KEY = 'ka:notifications_digest_cursor'

/** localStorage key prefix for the per-user persisted bell list. */
const NOTIFICATIONS_KEY_PREFIX = 'ka:notifications:'
const NOTIFICATIONS_KEY_ANON = 'ka:notifications:anon'
const MAX_BELL_ITEMS = 50

export function notificationsStorageKey(uid) {
  if (!uid) return NOTIFICATIONS_KEY_ANON
  return `${NOTIFICATIONS_KEY_PREFIX}${uid}`
}

export function loadStoredNotifications(uid) {
  try {
    const raw = localStorage.getItem(notificationsStorageKey(uid))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.slice(0, MAX_BELL_ITEMS)
  } catch {
    return []
  }
}

export function saveStoredNotifications(uid, items) {
  try {
    const arr = Array.isArray(items) ? items.slice(0, MAX_BELL_ITEMS) : []
    localStorage.setItem(notificationsStorageKey(uid), JSON.stringify(arr))
  } catch {
    /* noop */
  }
}

export function readDigestCursor() {
  try {
    return localStorage.getItem(NOTIF_DIGEST_CURSOR_KEY)
  } catch {
    return null
  }
}

export function writeDigestCursor(iso) {
  if (!iso) return
  try {
    localStorage.setItem(NOTIF_DIGEST_CURSOR_KEY, iso)
  } catch {
    /* noop */
  }
}

/**
 * Stable logical key per logical event so SSE + digest don't surface the same
 * request twice. Stored on each bell item so it can be reconstructed on rehydrate.
 */
export function notificationDedupeKey(d) {
  if (!d || typeof d !== 'object') return null
  if (d.type === 'opportunity_request.reviewed' && d.request_id && d.status) {
    return `r:${d.request_id}:${String(d.status).toUpperCase()}`
  }
  if (d.type === 'opportunity_request.created' && d.request_id) {
    return `c:${d.request_id}`
  }
  return null
}

const LOG = (...args) => {
  if (import.meta.env.DEV || String(import.meta.env.VITE_DEBUG_NOTIFICATIONS || '').toLowerCase() === 'true') {
    console.info('[notificationsDigest]', ...args)
  }
}

function digestUrl(after) {
  const q = `after=${encodeURIComponent(after)}`
  if (import.meta.env.DEV) {
    return `/notifications/digest?${q}`
  }
  const base = String(API_BASE || '').replace(/\/$/, '')
  return `${base}/notifications/digest?${q}`
}

/**
 * Pull missed opportunity-request notifications (reviews + admin: new PENDING rows).
 * Same payload shape as SSE so callers can re-dispatch window events.
 *
 * @param {{ afterIso: string }} opts
 * @returns {Promise<{ reviewed: object[], created: object[], next_cursor: string } | null>}
 */
export async function fetchNotificationsDigest({ afterIso }) {
  const token = await getAuthTokenForRequest()
  if (!token) {
    LOG('skip digest — no token')
    return null
  }
  const url = digestUrl(afterIso)
  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      cache: 'no-store',
    })
    if (!res.ok) {
      const t = await res.text().catch(() => '')
      LOG('digest HTTP', res.status, t?.slice(0, 200))
      return null
    }
    const data = await res.json()
    LOG('digest ok', { nReviewed: data?.reviewed?.length, nCreated: data?.created?.length, next: data?.next_cursor })
    return data
  } catch (e) {
    LOG('digest fetch failed', e?.message || e)
    return null
  }
}
