import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  updateProfile,
  sendPasswordResetEmail,
  GoogleAuthProvider,
  OAuthProvider,
  signInWithPopup,
  linkWithCredential,
  fetchSignInMethodsForEmail,
} from 'firebase/auth'
import { auth, isFirebaseConfigured } from '../config/firebase'
import { clearAuthTokenCookie, persistUserIdToken } from './authToken'
import { api } from './apiClient'

export const ORG_DOMAIN = import.meta.env.VITE_AUTH_EMAIL_DOMAIN || 'relanto.ai'
const MICROSOFT_PROVIDER_ID =
  import.meta.env.VITE_FIREBASE_MICROSOFT_PROVIDER_ID || 'oidc.azure-ad'

const SESSION_KEY = 'ka_session_user_v1'
const REGISTERED_DB_KEY = 'pzf_registered_db_user_v1'

function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase()
}

function getAvatar(name, email) {
  const fromName = String(name || '')
    .trim()
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase() || '')
    .join('')

  if (fromName) return fromName
  return normalizeEmail(email).slice(0, 2).toUpperCase() || 'KA'
}

export function isRelantoEmail(email) {
  const normalized = normalizeEmail(email)
  return normalized.endsWith(`@${ORG_DOMAIN}`)
}

function assertRelantoEmail(email) {
  if (!isRelantoEmail(email)) {
    throw new Error(`Only @${ORG_DOMAIN} email addresses are allowed.`)
  }
}

export function toSessionUserFromFirebase(fbUser) {
  const name = fbUser.displayName || fbUser.email?.split('@')[0] || 'User'
  return {
    name,
    email: normalizeEmail(fbUser.email),
    role: 'Knowledge User',
    avatar: getAvatar(fbUser.displayName, fbUser.email),
    uid: fbUser.uid,
  }
}

export function clearLocalSession() {
  try {
    localStorage.removeItem(SESSION_KEY)
  } catch {
    /* ignore */
  }
}

function _readRegisteredDbCache() {
  try {
    const raw = localStorage.getItem(REGISTERED_DB_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function _writeRegisteredDbCache(value) {
  try {
    localStorage.setItem(REGISTERED_DB_KEY, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

/**
 * Ensures backend has a `users` row linked to the Firebase user.
 * Backend: POST /api/auth/register (idempotent).
 *
 * - On sign-up: pass the exact name string typed by the user.
 * - On other sign-ins: pass Firebase `displayName` when available.
 */
async function ensureBackendUserRegistered(firebaseUser, name) {
  if (!firebaseUser) return
  const uid = String(firebaseUser.uid || '').trim()
  if (!uid) return

  const nameToSend = name == null ? null : String(name)
  const cached = _readRegisteredDbCache()
  if (cached?.uid === uid && cached?.name === nameToSend) return

  // Force-refresh so backend gets a fresh, valid token on first register.
  const idToken = await firebaseUser.getIdToken(true)

  const { data } = await api.post(
    '/api/auth/register',
    { name: nameToSend },
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${idToken}`,
      },
    },
  )

  if (data?.ok) {
    _writeRegisteredDbCache({ uid, name: nameToSend, at: Date.now() })
  }
  return data
}

/** Map Firebase Auth error codes to readable messages. */
export function mapFirebaseAuthError(err) {
  const code = err?.code || ''
  if (['auth/wrong-password', 'auth/invalid-credential', 'auth/user-not-found'].includes(code)) {
    return 'Invalid email or password.'
  }
  const messages = {
    'auth/unauthorized-domain':
      "This site's domain is not allowed for sign-in. In Firebase Console → Authentication → Settings → Authorized domains, add the host you use (e.g. localhost, 127.0.0.1, or your dev URL).",
    'auth/email-already-in-use': 'An account with this email already exists.',
    'auth/invalid-email': 'Please enter a valid email address.',
    'auth/weak-password': 'Password should be at least 6 characters.',
    'auth/too-many-requests': 'Too many attempts. Try again later.',
    'auth/popup-closed-by-user': 'Sign-in was cancelled.',
    'auth/account-exists-with-different-credential': 'This email is already used with another sign-in method.',
  }
  if (messages[code]) return messages[code]
  return err?.message || 'Authentication failed.'
}


export async function signInWithEmailPassword(email, password) {
  if (!auth) throw new Error('Firebase Auth is not configured. Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in .env')
  assertRelantoEmail(email)
  const cred = await signInWithEmailAndPassword(auth, normalizeEmail(email), String(password))
  await persistUserIdToken(cred.user)
  await ensureBackendUserRegistered(cred.user, cred.user?.displayName ?? null)
  clearLocalSession()
  return toSessionUserFromFirebase(cred.user)
}

export async function signUpWithEmailPassword({ name, email, password }) {
  if (!auth) throw new Error('Firebase Auth is not configured. Set VITE_FIREBASE_API_KEY and VITE_FIREBASE_AUTH_DOMAIN in .env')
  const rawName = name == null ? '' : String(name)
  const normalizedName = rawName.trim()
  if (!normalizedName) throw new Error('Full name is required.')
  if (String(password || '').length < 6) throw new Error('Password must be at least 6 characters.')
  assertRelantoEmail(email)

  let cred
  try {
    cred = await createUserWithEmailAndPassword(auth, normalizeEmail(email), String(password))
    await updateProfile(cred.user, { displayName: normalizedName })

    await persistUserIdToken(cred.user)
    // Ensure user exists in DB; send the exact string typed in the UI (rawName).
    await ensureBackendUserRegistered(cred.user, rawName)
    clearLocalSession()
    return toSessionUserFromFirebase(cred.user)
  } catch (err) {
    // If Firebase user exists but backend registration failed, rollback Firebase user
    // so user can retry sign-up cleanly.
    if (cred?.user) {
      try {
        await cred.user.delete()
      } catch {
        /* ignore */
      }
    }
    throw err
  }
}

export async function sendPasswordReset(email) {
  assertRelantoEmail(email)
  if (!auth) throw new Error('Firebase Auth is not configured.')
  await sendPasswordResetEmail(auth, normalizeEmail(email))
}

/**
 * @param {'google' | 'microsoft'} attemptedKind — which popup was used; needed for credentialFromError.
 */
async function signInWithPopupProvider(provider, providerLabel, attemptedKind) {
  try {
    const cred = await signInWithPopup(auth, provider)
    const em = cred.user.email
    if (!em || !isRelantoEmail(em)) {
      await signOut(auth)
      clearAuthTokenCookie()
      throw new Error(`Only @${ORG_DOMAIN} ${providerLabel} accounts are allowed.`)
    }
    const token = await persistUserIdToken(cred.user)
    if (!token) throw new Error('Could not obtain Firebase ID token.')

    await ensureBackendUserRegistered(cred.user, cred.user?.displayName ?? null)
    clearLocalSession()
    return toSessionUserFromFirebase(cred.user)
  } catch (err) {
    if (err?.code === 'auth/account-exists-with-different-credential' && auth) {
      const pendingCredential =
        attemptedKind === 'google'
          ? GoogleAuthProvider.credentialFromError(err)
          : OAuthProvider.credentialFromError(err)
      if (pendingCredential) {
        const email = err.customData?.email
        let existingSignInMethods = []
        if (email) {
          try {
            existingSignInMethods = await fetchSignInMethodsForEmail(auth, email)
          } catch {
            /* ignore */
          }
        }
        const enriched = new Error(err.message || 'Account exists with different credential')
        enriched.code = err.code
        enriched.email = email
        enriched.pendingCredential = pendingCredential
        enriched.attemptedProvider = attemptedKind
        enriched.existingSignInMethods = existingSignInMethods
        throw enriched
      }
    }
    throw err
  }
}

/**
 * After signing in with the provider that already owns this email, attach the pending OAuth credential
 * (e.g. Microsoft) so both providers work for the same Firebase user.
 */
export async function linkPendingCredential(pendingCredential) {
  if (!auth) throw new Error('Firebase Auth is not configured.')
  const u = auth.currentUser
  if (!u) throw new Error('Sign in with your existing account first, then linking completes.')
  if (!pendingCredential) throw new Error('Nothing to link.')
  const linked = await linkWithCredential(u, pendingCredential)
  await persistUserIdToken(linked.user)
  clearLocalSession()
  return toSessionUserFromFirebase(linked.user)
}

export async function signInWithGoogle() {
  if (!auth) throw new Error('Firebase Auth is not configured.')
  const provider = new GoogleAuthProvider()
  provider.setCustomParameters({ prompt: 'select_account' })
  return signInWithPopupProvider(provider, 'Google', 'google')
}

/** Microsoft / Azure AD via Firebase OAuthProvider (default `oidc.azure-ad`). */
export async function signInWithMicrosoft() {
  if (!auth) throw new Error('Firebase Auth is not configured.')
  const provider = new OAuthProvider(MICROSOFT_PROVIDER_ID)
  provider.setCustomParameters({ prompt: 'select_account' })
  return signInWithPopupProvider(provider, 'Microsoft', 'microsoft')
}

export async function signOutUser() {
  clearLocalSession()
  clearAuthTokenCookie()
  if (auth) {
    await signOut(auth)
  }
}

export function subscribeAuth(callback) {
  if (!isFirebaseConfigured || !auth) {
    queueMicrotask(() => callback(null))
    return () => {}
  }

  return onAuthStateChanged(auth, (fbUser) => {
    if (!fbUser) {
      clearAuthTokenCookie()
      callback(null)
      return
    }
    const em = fbUser.email
    if (em && !isRelantoEmail(em)) {
      signOut(auth).catch(() => {})
      clearAuthTokenCookie()
      callback(null)
      return
    }
    persistUserIdToken(fbUser).catch(() => {})
    clearLocalSession()
    callback(toSessionUserFromFirebase(fbUser))
  })
}

export { isFirebaseConfigured }
