import { API_BASE } from './apiClient'
import { getAuthTokenForRequest } from './authToken'

const LOG = (...args) => {
  if (import.meta.env.DEV || String(import.meta.env.VITE_DEBUG_NOTIFICATIONS || '').toLowerCase() === 'true') {
    console.info('[notificationsStream]', ...args)
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

/**
 * URL for GET /notifications/stream.
 * In dev, use a path-relative URL so Vite's proxy always forwards to the API (same as axios baseURL '').
 */
export function getNotificationsStreamUrl() {
  if (import.meta.env.DEV) {
    return '/notifications/stream'
  }
  const base = String(API_BASE || '').replace(/\/$/, '')
  return `${base}/notifications/stream`
}

/**
 * Parse one SSE block (lines ending before blank line was stripped).
 * @param {string} block
 * @returns {Record<string, unknown> | null}
 */
function parseSseBlock(block) {
  const lines = block.replace(/\r\n/g, '\n').split('\n').filter(Boolean)
  let dataLine = ''
  for (const line of lines) {
    if (line.startsWith('data:')) {
      dataLine = line.slice(5).trim()
    }
  }
  if (!dataLine) return null
  try {
    return JSON.parse(dataLine)
  } catch {
    return null
  }
}

async function waitForAuthToken(maxAttempts = 20, delayMs = 250) {
  for (let i = 0; i < maxAttempts; i += 1) {
    const token = await getAuthTokenForRequest()
    if (token) {
      if (i > 0) LOG('token became available after', i, 'retries')
      return token
    }
    await sleep(delayMs)
  }
  LOG('no auth token after retries — cannot open SSE')
  return null
}

/**
 * Long-lived GET /notifications/stream with Bearer token (EventSource cannot set headers).
 *
 * @param {{ onMessage: (data: Record<string, unknown>) => void, signal?: AbortSignal }} opts
 */
export async function consumeNotificationsStream({ onMessage, signal }) {
  const url = getNotificationsStreamUrl()
  LOG('opening SSE', url)

  const token = await waitForAuthToken()
  if (!token) {
    return
  }

  let res
  try {
    res = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token}`,
      },
      signal,
      cache: 'no-store',
    })
  } catch (e) {
    LOG('fetch failed', e?.message || e)
    throw e
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    LOG('SSE HTTP error', res.status, text?.slice(0, 200))
    return
  }

  if (!res.body) {
    LOG('SSE missing response body')
    return
  }

  LOG('SSE connected', res.status, res.headers.get('content-type'))

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      LOG('SSE reader done (server closed stream)')
      break
    }
    buffer += decoder.decode(value, { stream: true })
    buffer = buffer.replace(/\r\n/g, '\n')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const rawBlock of parts) {
      if (rawBlock.startsWith(':')) continue
      const data = parseSseBlock(rawBlock)
      if (data && typeof data === 'object') {
        LOG('SSE event', data.type || '(no type)', data)
        onMessage(data)
      }
    }
  }
}
