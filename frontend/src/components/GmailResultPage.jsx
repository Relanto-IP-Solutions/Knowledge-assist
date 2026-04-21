/**
 * GmailResultPage
 *
 * Served at `/gmail-result` — the backend redirects the OAuth popup here after
 * completing a Gmail authorisation flow (discover or per-opportunity connect).
 *
 * Query params set by the backend:
 *   gmail_discover = 'success' | 'error'
 *   gmail_connect  = 'success' | 'error'
 *   oid            = opportunity id (connect flow only)
 *   threads_scanned, opportunities_created  (discover success)
 *   error          = human-readable error string
 *
 * Behaviour
 * ─────────
 * • Popup (window.opener exists): sends a postMessage to the opener then closes.
 * • Full-page redirect fallback: renders a brief status screen, then navigates to /.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchGmailConnectInfo,
  connectGmail,
  fetchGmailMetrics,
  getGmailBackendRedirectUri,
  getGmailFrontendResultUrl,
} from '../services/integrationsAuthApi'
import {
  GMAIL_CONNECTOR_EMAIL_SESSION_KEY,
  gmailConnectorEmailSessionKey,
} from '../hooks/useGmailConnector'

export default function GmailResultPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState('processing') // 'processing' | 'done' | 'error'
  const [message, setMessage] = useState('')
  const [payloadState, setPayloadState] = useState(null)
  const [statusMessage, setStatusMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    let timer

    const params = new URLSearchParams(window.location.search)
    const gmailDiscover = params.get('gmail_discover')
    const gmailConnect  = params.get('gmail_connect')
    const oid           = params.get('oid')
    const errorMsg      = params.get('error')

    const isSuccess = gmailDiscover === 'success' || gmailConnect === 'success'
    const isError   = gmailDiscover === 'error'   || gmailConnect === 'error' || !!errorMsg

    const payload = {
      type: 'gmail_oauth_result',
      gmailDiscover,
      gmailConnect,
      oid,
      error: errorMsg,
      threadsScanned:       Number(params.get('threads_scanned')       ?? 0),
      threadsWithOid:       Number(params.get('threads_with_oid')      ?? 0),
      opportunitiesCreated: Number(params.get('opportunities_created') ?? 0),
      opportunitySourcesCreated: Number(params.get('opportunity_sources_created') ?? 0),
      success: isSuccess && !isError,
    }
    setPayloadState(payload)

    if (window.opener && !window.opener.closed) {
      // Popup flow — run API sequence then postMessage to parent and close
      ;(async () => {
        if (!isSuccess || isError || !oid) {
          try { window.opener.postMessage({ ...payload, success: false }, window.location.origin) } catch { /**/ }
          window.close()
          return
        }

        // Resolve user_email from sessionStorage (written by GmailOpportunityCard before opening the tab)
        const userEmail = (() => {
          try {
            const scoped = sessionStorage.getItem(gmailConnectorEmailSessionKey(oid))
            if (scoped) return scoped
            return sessionStorage.getItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY) || ''
          } catch { return '' }
        })()

        if (!userEmail) {
          try {
            window.opener.postMessage({
              ...payload,
              success: false,
              error: 'Gmail address not found — please retry',
            }, window.location.origin)
          } catch { /**/ }
          window.close()
          return
        }

        try {
          // Step 1: connect-info gate
          setStatusMessage('Checking authorisation…')
          const connectInfo = await fetchGmailConnectInfo(oid)
          if (connectInfo?.status === 'UNAUTHORIZED') {
            throw new Error('Gmail auth failed — please try again.')
          }

          // Step 2: connect (synchronous ingest, ~5-10s)
          setStatusMessage('Syncing project data…')
          const connectResult = await connectGmail(
            oid,
            getGmailBackendRedirectUri(),
            userEmail,
            getGmailFrontendResultUrl(),
          )

          // Step 3: metrics
          setStatusMessage('Loading metrics…')
          let metrics = null
          try {
            metrics = await fetchGmailMetrics(oid, userEmail)
          } catch {
            // metrics failure is non-fatal — still postMessage with connectResult
          }

          // Step 4: postMessage full result to parent tab
          try {
            window.opener.postMessage({
              ...payload,
              gmailConnect: 'success',
              connectResult,
              metrics,
              success: true,
            }, window.location.origin)
          } catch { /**/ }

        } catch (err) {
          try {
            window.opener.postMessage({
              ...payload,
              success: false,
              error: err?.message || 'Gmail connect failed — please retry.',
            }, window.location.origin)
          } catch { /**/ }
        }

        window.close()
      })()

      return undefined
    }

    // Full-page fallback — hydrate metrics cache (backend may have already synced), then navigate
    ;(async () => {
      const mailbox = (() => {
        try {
          if (oid) {
            const scoped = sessionStorage.getItem(gmailConnectorEmailSessionKey(oid))
            if (scoped) return scoped
          }
          return sessionStorage.getItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY) || undefined
        } catch {
          return undefined
        }
      })()

      if (!isError && oid && isSuccess) {
        try {
          await fetchGmailMetrics(oid, mailbox)
        } catch {
          /* metrics route optional — Sources page will re-fetch */
        }
      }

      if (cancelled) return

      if (isError) {
        setStatus('error')
        setMessage(errorMsg || 'Gmail authorisation failed. Please try again.')
      } else if (isSuccess) {
        setStatus('done')
        setMessage(gmailConnect === 'success' ? 'Gmail connected successfully.' : 'Gmail scan complete.')
      } else {
        setStatus('done')
        setMessage('Returning…')
      }

      timer = setTimeout(() => {
        if (cancelled) return
        navigate('/')
      }, 1700)
    })()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [navigate])

  const icon = status === 'error'
    ? '✕'
    : status === 'done' ? '✓' : null

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg, #F8FAFC)', fontFamily: "'Plus Jakarta Sans', sans-serif",
      gap: 16, padding: 32,
    }}>
      {/* Gmail logo */}
      <svg width="40" height="40" viewBox="0 0 48 48" aria-hidden>
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6C44.21 37.2 46.98 31.49 46.98 24.55z"/>
        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
      </svg>

      {/* Spinner while waiting for popup to close */}
      {status === 'processing' && (
        <svg style={{ animation: 'spin .9s linear infinite' }} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#EA4335" strokeWidth="2.5" strokeLinecap="round">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
      )}

      {icon && (
        <div style={{
          width: 40, height: 40, borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: status === 'error' ? 'rgba(220,38,38,.1)' : 'rgba(16,185,129,.1)',
          color: status === 'error' ? '#DC2626' : '#059669',
          fontSize: 20, fontWeight: 800,
        }}>{icon}</div>
      )}

      <div style={{
        fontSize: 14, fontWeight: 600, color: status === 'error' ? '#DC2626' : 'var(--text0, #0F172A)',
        textAlign: 'center', maxWidth: 320,
      }}>
        {status === 'processing'
          ? (statusMessage || 'Completing Gmail authorisation…')
          : message}
      </div>

      {status !== 'processing' && (
        status === 'error' ? (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={() => navigate('/')}
              style={{
                border: '1px solid rgba(27,38,79,.18)', background: '#fff', color: 'var(--text2, #475569)',
                borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 700,
              }}
            >
              Back to dashboard
            </button>
            <button
              type="button"
              onClick={() => navigate('/')}
              style={{
                border: '1px solid rgba(234,67,53,.35)', background: 'rgba(234,67,53,.08)', color: '#EA4335',
                borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 800,
              }}
            >
              Retry Discover
            </button>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--text2, #64748B)' }}>
            Redirecting you back…
          </div>
        )
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
