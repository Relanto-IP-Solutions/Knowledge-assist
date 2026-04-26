import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { toApiOpportunityId } from '../config/opportunityApi'
import {
  connectOneDrive,
  fetchOneDriveMetrics,
  getMicrosoftOAuthUrl,
  getOneDriveOAuthRedirectUri,
  getCachedOneDriveMetrics,
  getOneDriveAuthorizeInfo,
} from '../services/integrationsAuthApi'
import { OneDriveIcon } from './SourceIcons'

const OD_BLUE    = '#0078D4'
const NAVY       = '#1B264F'
const GREEN      = '#10B981'
const RELANTO_RE = /@relanto\.ai$/i
const EMAIL_RE   = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const SS_EMAIL         = (oid) => `pzf_onedrive_email_${oid}`
const SS_PENDING_OID   = 'pzf_onedrive_pending_oid'
const SS_PENDING_EMAIL = 'pzf_onedrive_pending_email'

function ssGet(k) { try { return sessionStorage.getItem(k) } catch { return null } }
function ssSet(k, v) { try { sessionStorage.setItem(k, v) } catch { /**/ } }
function ssDel(k) { try { sessionStorage.removeItem(k) } catch { /**/ } }

function timeAgo(iso) {
  if (!iso) return null
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function SpinIcon({ size = 13 }) {
  return (
    <svg style={{ animation: 'odSpin .9s linear infinite', flexShrink: 0 }}
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
  )
}

function Dot({ active }) {
  const c = active ? GREEN : '#CBD5E1'
  return (
    <span style={{ position: 'relative', width: 8, height: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      {active && <span style={{ position: 'absolute', width: 8, height: 8, borderRadius: '50%', background: c, animation: 'odPulseRing 1.6s ease-out infinite' }} />}
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, position: 'relative' }} />
    </span>
  )
}

function EmailModal({ oid, onSubmit, onCancel }) {
  const [value, setValue] = useState('')
  const [localErr, setLocalErr] = useState('')

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const submit = () => {
    const t = value.trim()
    if (!t) { setLocalErr('Enter your Microsoft account email.'); return }
    if (!EMAIL_RE.test(t)) { setLocalErr('Enter a valid email address.'); return }
    if (!RELANTO_RE.test(t)) { setLocalErr('Only @relanto.ai accounts are permitted.'); return }
    setLocalErr('')
    onSubmit(t.toLowerCase())
  }

  return createPortal(
    <div onClick={onCancel} style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(15,23,42,.55)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, animation: 'odFadeIn .15s ease',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: '100%', maxWidth: 420, background: 'var(--bg2, #fff)', borderRadius: 16,
        boxShadow: '0 24px 64px rgba(15,23,42,.22)', overflow: 'hidden',
        animation: 'odSlideUp .18s ease', fontFamily: 'var(--font)',
      }}>
        <div style={{ padding: '20px 24px 12px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 800, color: NAVY }}>
            Connect OneDrive for this project
          </h3>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--text2)', lineHeight: 1.55 }}>
            Enter your <strong style={{ color: NAVY }}>@relanto.ai</strong> Microsoft account email for project{' '}
            <strong style={{ color: NAVY }}>{oid}</strong>.
          </p>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: NAVY, marginBottom: 6 }}>
            Microsoft account email
          </label>
          <input
            type="email" autoComplete="email" value={value}
            onChange={e => { setValue(e.target.value); setLocalErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="you@relanto.ai"
            style={{
              width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: 10,
              border: `1.5px solid ${localErr ? '#DC2626' : 'rgba(27,38,79,.15)'}`,
              fontSize: 13, fontFamily: 'var(--font)', outline: 'none',
            }}
          />
          {localErr && <p style={{ margin: '8px 0 0', fontSize: 11, color: '#DC2626', fontWeight: 600 }}>{localErr}</p>}
        </div>
        <div style={{ padding: '0 24px 20px', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancel} style={{
            padding: '8px 18px', borderRadius: 8, border: '1.5px solid rgba(27,38,79,.15)',
            background: 'transparent', color: 'var(--text2)', fontSize: 12, fontWeight: 600,
            cursor: 'pointer', fontFamily: 'var(--font)',
          }}>Cancel</button>
          <button type="button" onClick={submit} style={{
            padding: '8px 20px', borderRadius: 8, border: `1.5px solid ${OD_BLUE}`,
            background: OD_BLUE, color: '#fff', fontSize: 12, fontWeight: 700,
            cursor: 'pointer', fontFamily: 'var(--font)',
          }}>Connect</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function OneDriveOpportunityCard({ opportunityId, onStatusChange }) {
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])

  const [metrics, setMetrics]               = useState(() => getCachedOneDriveMetrics(oid))
  const [metricsLoading, setMetricsLoading] = useState(() => getCachedOneDriveMetrics(oid) === null)
  const [busy, setBusy]                     = useState(false)
  const [showModal, setShowModal]           = useState(false)
  const [userEmail, setUserEmail]           = useState(() => ssGet(SS_EMAIL(oid)) ?? '')
  const [notice, setNotice]                 = useState(null) // { type: 'success'|'error', msg }

  const mountedRef = useRef(true)
  const oidRef     = useRef(oid)
  oidRef.current   = oid

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false } }, [])

  const isActive = String(metrics?.status ?? '').toUpperCase() === 'ACTIVE'

  useEffect(() => { onStatusChange?.(isActive) }, [isActive, onStatusChange])

  // Load metrics on mount. Header status is derived from the cached value seeded above; this
  // fetch only updates state once the backend responds. An 8s soft timeout guards against a
  // slow/hanging metrics call so the UI never sticks in a loading state.
  useEffect(() => {
    let alive = true
    const ac = new AbortController()
    const timeoutId = setTimeout(() => ac.abort(), 8000)

    const hasCache = getCachedOneDriveMetrics(oid) !== null
    if (!hasCache) setMetricsLoading(true)

    fetchOneDriveMetrics(oid, { signal: ac.signal })
      .then(m => { if (alive) setMetrics(m) })
      .catch(() => { /** silent: keep cached value (or null), header falls back to "Not connected". */ })
      .finally(() => {
        clearTimeout(timeoutId)
        if (alive) setMetricsLoading(false)
      })

    return () => {
      alive = false
      clearTimeout(timeoutId)
      ac.abort()
    }
  }, [oid])

  // OAuth return: auto-connect after redirect
  useEffect(() => {
    const pendingOid   = ssGet(SS_PENDING_OID)
    const pendingEmail = ssGet(SS_PENDING_EMAIL)
    if (!pendingOid || pendingOid !== oid || !pendingEmail) return
    ssDel(SS_PENDING_OID)
    ssDel(SS_PENDING_EMAIL)
    setUserEmail(pendingEmail)
    ssSet(SS_EMAIL(oid), pendingEmail)
    void runConnectAndMetrics(oid, pendingEmail)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const doRedirect = useCallback((runOid, email, authUrl) => {
    ssSet(SS_PENDING_OID, runOid)
    ssSet(SS_PENDING_EMAIL, email)
    window.location.href = String(authUrl).trim()
  }, [])

  // Core: POST connect (always) → GET metrics (always)
  const runConnectAndMetrics = useCallback(async (runOid, email) => {
    if (!mountedRef.current) return
    setBusy(true)
    setNotice(null)

    let folderError = null

    try {
      await connectOneDrive(runOid, email)
    } catch (e) {
      if (!mountedRef.current || oidRef.current !== runOid) return
      const status = e?.response?.status
      const detail = e?.response?.data?.detail ?? ''

      if (status === 401 || status === 400) {
        // Token expired/missing — redirect to OAuth
        try {
          const auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, runOid)
          if (auth?.auth_url) { doRedirect(runOid, email, auth.auth_url); return }
        } catch { /**/ }
        if (mountedRef.current) {
          setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
          setBusy(false)
        }
        return
      }

      if (status === 403) {
        setNotice({ type: 'error', msg: 'Only @relanto.ai accounts are permitted.' })
        setBusy(false)
        return
      }

      // 404 folder-not-found — surface message but still fetch metrics
      folderError = detail || 'Folder not found for this OID. Create it in OneDrive and click Resync.'
      setNotice({ type: 'error', msg: folderError })
    }

    if (!mountedRef.current || oidRef.current !== runOid) return

    if (!folderError) setNotice({ type: 'info', msg: 'Syncing your OneDrive files…' })

    // Poll metrics every 3s until status === ACTIVE (max 20 attempts = 60s)
    const POLL_INTERVAL = 3000
    const MAX_ATTEMPTS  = 20
    let lastMetrics = null
    for (let i = 0; i < MAX_ATTEMPTS; i++) {
      if (!mountedRef.current || oidRef.current !== runOid) return
      try {
        const m = await fetchOneDriveMetrics(runOid)
        lastMetrics = m
        if (mountedRef.current) setMetrics(m)
        if (String(m?.status ?? '').toUpperCase() === 'ACTIVE') break
      } catch { /**/ }
      if (i < MAX_ATTEMPTS - 1) await new Promise(r => setTimeout(r, POLL_INTERVAL))
    }

    if (mountedRef.current && oidRef.current === runOid) {
      if (lastMetrics) setMetrics(lastMetrics)
      if (!folderError) {
        const fileCount = Number(lastMetrics?.total_files ?? 0)
        setNotice({
          type: fileCount > 0 ? 'success' : 'info',
          msg: fileCount > 0
            ? 'Sync complete! Your files are ready.'
            : 'Connected. Files are still being indexed — check back shortly.',
        })
      }
      setBusy(false)
    }
  }, [doRedirect])

  // ── Connect flow ─────────────────────────────────────────────────
  const handleConnectWithEmail = useCallback(async (email) => {
    setShowModal(false)
    setUserEmail(email)
    ssSet(SS_EMAIL(oid), email)
    setBusy(true)
    setNotice(null)

    let auth = null
    try {
      auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, oid)
    } catch (e) {
      if (!mountedRef.current) return
      const status = e?.response?.status
      if (status === 403) {
        setNotice({ type: 'error', msg: 'Only @relanto.ai accounts are permitted.' })
        setBusy(false)
        return
      }
      // Error body might still carry an auth_url
      const authUrl = e?.response?.data?.auth_url
      if (authUrl) { doRedirect(oid, email, authUrl); return }
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setBusy(false)
      return
    }

    if (!mountedRef.current) return

    if (auth?.already_connected === true) {
      await runConnectAndMetrics(oid, email)
    } else if (auth?.auth_url) {
      doRedirect(oid, email, auth.auth_url)
    } else {
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setBusy(false)
    }
  }, [oid, doRedirect, runConnectAndMetrics])

  const handleConnect = useCallback(() => {
    setNotice(null)
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (!email || !RELANTO_RE.test(email)) { setShowModal(true); return }
    void handleConnectWithEmail(email)
  }, [oid, userEmail, handleConnectWithEmail])

  // ── Resync flow ──────────────────────────────────────────────────
  const handleResync = useCallback(async () => {
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (!email) { setShowModal(true); return }

    setBusy(true)
    setNotice(null)

    // Step 1: check authorize-info to confirm connection exists
    let authorizeInfo = null
    try {
      authorizeInfo = await getOneDriveAuthorizeInfo(oid, email)
    } catch { /* unknown — proceed to connect and let it decide */ }

    if (!mountedRef.current || oidRef.current !== oid) return

    if (authorizeInfo?.has_onedrive_connection === false) {
      // No connection — route to OAuth
      try {
        const auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, oid)
        if (auth?.auth_url) { doRedirect(oid, email, auth.auth_url); return }
      } catch { /**/ }
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setBusy(false)
      return
    }

    // Connection exists (or unknown) — run connect + metrics
    await runConnectAndMetrics(oid, email)
  }, [oid, userEmail, doRedirect, runConnectAndMetrics])

  const totalFilesCount = Number(metrics?.total_files ?? 0)
  const noticeColor = notice?.type === 'success' ? '#047857' : notice?.type === 'info' ? OD_BLUE : '#DC2626'

  return (
    <>
      <style>{`
        @keyframes odSpin       { to { transform: rotate(360deg) } }
        @keyframes odPulseRing  { 0%{transform:scale(1);opacity:.6}70%{transform:scale(2.2);opacity:0}100%{transform:scale(1);opacity:0} }
        @keyframes odFadeIn     { from{opacity:0} to{opacity:1} }
        @keyframes odSlideUp    { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }
      `}</style>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 22px', borderBottom: isActive ? '1px solid var(--border)' : 'none',
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: 'rgba(0,120,212,.06)', border: '1.5px solid rgba(0,120,212,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <OneDriveIcon size={22} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>OneDrive</span>
            <Dot active={isActive} />
            <span style={{ fontSize: 11, color: isActive ? GREEN : '#94A3B8', fontWeight: 600 }}>
              {isActive ? 'Active' : 'Not connected'}
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Microsoft OneDrive Files</div>
          {userEmail && (
            <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2 }}>
              <span style={{ fontWeight: 600 }}>Account: </span>
              <span style={{ color: NAVY, fontWeight: 700 }}>{userEmail}</span>
            </div>
          )}
        </div>

        {/* Connect — not active */}
        {!isActive && (
          <button type="button" disabled={busy} onClick={handleConnect}
            style={{
              flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${OD_BLUE}`, background: OD_BLUE, color: '#fff',
              fontFamily: 'var(--font)', opacity: busy ? 0.55 : 1, transition: 'opacity .12s',
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Connecting…' : 'Connect OneDrive'}
          </button>
        )}

        {/* Resync — active */}
        {isActive && (
          <button type="button" disabled={busy} onClick={handleResync}
            style={{
              flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${OD_BLUE}`, background: 'rgba(0,120,212,.1)', color: OD_BLUE,
              fontFamily: 'var(--font)', opacity: busy ? 0.55 : 1, transition: 'opacity .12s',
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Syncing…' : 'Resync Items'}
          </button>
        )}
      </div>

      {/* Notice */}
      {notice && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: noticeColor }}>{notice.msg}</span>
        </div>
      )}

      {/* Metrics */}
      {isActive && metrics && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(0,120,212,.15)',
            background: 'rgba(0,120,212,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '9px 16px 8px', borderBottom: '1px solid rgba(0,120,212,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={OD_BLUE} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: OD_BLUE }}>
                Sync metadata
              </span>
              {metricsLoading && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 6, color: OD_BLUE, opacity: .8 }}>
                  <SpinIcon size={9} />
                  <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase' }}>Refreshing</span>
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 16px 16px' }}>
              <div style={{
                flex: '1 1 120px', padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(0,120,212,.1)' : 'none',
              }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>Total files</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span style={{ fontSize: 22, fontWeight: 800, color: NAVY, lineHeight: 1 }}>{totalFilesCount}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--text2)' }}>{totalFilesCount === 1 ? 'file' : 'files'}</span>
                </div>
              </div>
              {metrics?.last_synced_at && (
                <div style={{ flex: '1 1 140px', padding: '4px 0' }}>
                  <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>Last synced</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: NAVY }}>{timeAgo(metrics.last_synced_at)}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 4 }}>
                    {new Date(metrics.last_synced_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <EmailModal oid={oid} onSubmit={handleConnectWithEmail} onCancel={() => setShowModal(false)} />
      )}
    </>
  )
}
