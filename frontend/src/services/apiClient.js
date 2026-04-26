import axios from 'axios'
import { getAuthTokenForRequest, isJwtDebugLoggingEnabled } from './authToken'

const RAW_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
/**
 * In dev we proxy API requests via Vite (see `vite.config.js`) so the browser sees same-origin calls
 * and we avoid CORS during local development.
 */
const baseURL = import.meta.env.DEV ? '' : String(RAW_BASE).replace(/\/$/, '')

/**
 * Full backend base URL (with scheme + host). Use for:
 * - EventSource / SSE streams that need absolute URLs
 * - OAuth redirect_uri construction
 * - Dev console logging
 * In dev, resolves to window.location.origin (same-origin via Vite proxy).
 * In production, resolves to VITE_API_BASE.
 */
export const API_BASE = import.meta.env.DEV
  ? window.location.origin
  : String(RAW_BASE).replace(/\/$/, '')

export const api = axios.create({
  baseURL,
  headers: {
    Accept: 'application/json',
  },
})

api.interceptors.request.use(async (config) => {
  // Attach a per-request correlation ID so frontend and backend logs can be matched.
  const rid = Math.random().toString(36).slice(2, 11)
  if (config.headers && typeof config.headers.set === 'function') {
    config.headers.set('x-request-id', rid)
  } else {
    config.headers = { ...(config.headers || {}), 'x-request-id': rid }
  }

  const token = await getAuthTokenForRequest()
  if (token) {
    if (config.headers && typeof config.headers.set === 'function') {
      config.headers.set('Authorization', `Bearer ${token}`)
    } else {
      config.headers = { ...(config.headers || {}), Authorization: `Bearer ${token}` }
    }
    if (isJwtDebugLoggingEnabled()) {
      const u = config.url != null ? String(config.url) : ''
      console.info(`[apiClient] JWT for ${String(config.method || 'get').toUpperCase()} ${u}  rid=${rid}\n`, token)
    }
  }
  return config
})

