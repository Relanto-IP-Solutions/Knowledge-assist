import Cookies from 'js-cookie'
import { auth } from '../config/firebase'

export const AUTH_TOKEN_COOKIE_KEY = 'pzf_firebase_id_token'

/** Dev-only: set `VITE_DEBUG_LOG_JWT=true` in `.env` and restart Vite. */
export function isJwtDebugLoggingEnabled() {
  if (!import.meta.env.DEV) return false
  const v = String(import.meta.env.VITE_DEBUG_LOG_JWT ?? '').trim().toLowerCase()
  return v === 'true' || v === '1' || v === 'yes'
}

function cookieOptions() {
  const secure =
    typeof window !== 'undefined' && window.location?.protocol === 'https:'
  return { sameSite: 'strict', secure, path: '/' }
}

export function setAuthTokenCookie(token) {
  const t = String(token || '').trim()
  if (!t) return
  Cookies.set(AUTH_TOKEN_COOKIE_KEY, t, cookieOptions())
}

export function getAuthTokenCookie() {
  const t = Cookies.get(AUTH_TOKEN_COOKIE_KEY)
  return t ? String(t) : null
}

export function clearAuthTokenCookie() {
  Cookies.remove(AUTH_TOKEN_COOKIE_KEY, { path: '/' })
}

export async function persistUserIdToken(user) {
  if (!user) return null
  const token = await user.getIdToken()
  setAuthTokenCookie(token)
  if (isJwtDebugLoggingEnabled() && token) {
    console.info('[auth] Firebase ID token (JWT) after sign-in — copy for backend tests:\n', token)
  }
  return token
}

/**
 * Returns the best available token for API requests.
 * Prefers a fresh Firebase ID token (and persists it in cookies), falling back to cookie value.
 */
export async function getAuthTokenForRequest() {
  if (auth?.currentUser) {
    try {
      const token = await auth.currentUser.getIdToken()
      if (token) setAuthTokenCookie(token)
      return token || null
    } catch {
      /* ignore */
    }
  }
  return getAuthTokenCookie()
}

