/**
 * Firebase client config (same project as Google Identity Platform when enabled in GCP).
 * Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in `.env` (see `.env.example`).
 *
 * Web API keys are not secret; lock down with Firebase App Check + Auth domain / OAuth restrictions in Google Cloud.
 */
import { initializeApp, getApps } from 'firebase/app'
import { getAuth } from 'firebase/auth'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || '',
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || '',
}

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain,
)

let app = null
if (isFirebaseConfigured) {
  app = getApps().length > 0 ? getApps()[0] : initializeApp(firebaseConfig)
}

/** @type {import('firebase/auth').Auth | null} */
export const auth = app ? getAuth(app) : null
