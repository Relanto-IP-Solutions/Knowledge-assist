import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { toApiOpportunityId } from '../config/opportunityApi'
import {
  connectDrive,
  fetchDriveMetrics,
  getCachedDriveMetrics,
  getDriveAuthUrl,
  getDriveOAuthRedirectUri,
} from '../services/integrationsAuthApi'
import { GDriveIcon } from './SourceIcons'
import { isWorkspacePolicyError, WORKSPACE_POLICY_ERROR_MSG } from '../utils/gmailErrorMapper'

const DRIVE_BLUE = '#4285F4'
const NAVY       = '#1B264F'
const GREEN      = '#10B981'
const EMAIL_RE   = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const SS_EMAIL         = (oid) => `pzf_drive_email_${oid}`
const SS_PENDING_OID   = 'pzf_drive_pending_oid'
const SS_PENDING_EMAIL = 'pzf_drive_pending_email'

function ssGet(key) { try { return sessionStorage.getItem(key) } catch { return null } }
function ssSet(key, val) { try { sessionStorage.setItem(key, val) } catch { /**/ } }
function ssDel(key) { try { sessionStorage.removeItem(key) } catch { /**/ } }

function timeAgo(iso) {
  if (!iso) return null
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function SpinIcon({ size = 13 }) {
  return (
    <svg style={{ animation: 'drSpin .9s linear infinite', flexShrink: 0 }}
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
  )
}

function Dot({ active }) {
  const c = active ? GREEN : '#CBD5E1'
  return (
    <span style={{ position: 'relative', width: 8, height: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      {active && <span style={{ position: 'absolute', width: 8, height: 8, borderRadius: '50%', background: c, animation: 'drPulseRing 1.6s ease-out infinite' }} />}
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
    if (!t) { setLocalErr('Enter a Google account email.'); return }
    if (!EMAIL_RE.test(t)) { setLocalErr('Enter a valid email address.'); return }
    setLocalErr('')
    onSubmit(t.toLowerCase())
  }

  return createPortal(
    <div onClick={onCancel} style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(15,23,42,.55)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, animation: 'drFadeIn .15s ease',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: '100%', maxWidth: 420, background: 'var(--bg2, #fff)', borderRadius: 16,
        boxShadow: '0 24px 64px rgba(15,23,42,.22)', overflow: 'hidden',
        animation: 'drSlideUp .18s ease', fontFamily: 'var(--font)',
      }}>
        <div style={{ padding: '20px 24px 12px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 800, color: NAVY }}>
            Connect Google Drive for this project
          </h3>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--text2)', lineHeight: 1.55 }}>
            Enter the Google account for project <strong style={{ color: NAVY }}>{oid}</strong>.
          </p>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: NAVY, marginBottom: 6 }}>
            Google account email
          </label>
          <input
            type="email" autoComplete="email" value={value}
            onChange={e => { setValue(e.target.value); setLocalErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="example@company.com"
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
            padding: '8px 20px', borderRadius: 8, border: `1.5px solid ${DRIVE_BLUE}`,
            background: DRIVE_BLUE, color: '#fff', fontSize: 12, fontWeight: 700,
            cursor: 'pointer', fontFamily: 'var(--font)',
          }}>Connect</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function DriveOpportunityCard({ opportunityId, onStatusChange }) {
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])

  const [metrics, setMetrics]               = useState(() => getCachedDriveMetrics(oid))
  /** Only used to render a small in-card spinner inside the metrics block on first ever load. The
   * header status is now derived deterministically from the cached/last-known status. */
  const [metricsLoading, setMetricsLoading] = useState(() => getCachedDriveMetrics(oid) === null)
  const [busy, setBusy]                     = useState(false)
  const [syncStatus, setSyncStatus]         = useState(null) // 'connecting' | 'success' | null
  const [showModal, setShowModal]           = useState(false)
  const [userEmail, setUserEmail]           = useState(() => ssGet(SS_EMAIL(oid)) ?? '')
  const [err, setErr]                       = useState(null)

  const mountedRef = useRef(true)
  const oidRef     = useRef(oid)
  oidRef.current   = oid

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const isActive = String(metrics?.status ?? '').toUpperCase() === 'ACTIVE'

  useEffect(() => { onStatusChange?.(isActive) }, [isActive, onStatusChange])

  // ── Step 1: Background-refresh metrics on mount. Header status is derived from the cached
  // value (seeded above); this fetch only updates state once the backend responds. An 8s soft
  // timeout prevents a slow/hanging GCS list call from pinning the UI in a loading state.
  useEffect(() => {
    let alive = true
    const ac = new AbortController()
    const timeoutId = setTimeout(() => ac.abort(), 8000)

    setErr(null)
    if (getCachedDriveMetrics(oid) === null) setMetricsLoading(true)

    fetchDriveMetrics(oid, undefined, { signal: ac.signal })
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

  // ── Auto-sync after returning from Google OAuth ───────────────────
  useEffect(() => {
    const pendingOid   = ssGet(SS_PENDING_OID)
    const pendingEmail = ssGet(SS_PENDING_EMAIL)
    if (!pendingOid || pendingOid !== oid || !pendingEmail) return
    ssDel(SS_PENDING_OID)
    ssDel(SS_PENDING_EMAIL)
    setUserEmail(pendingEmail)
    ssSet(SS_EMAIL(oid), pendingEmail)
    void runSync(oid, pendingEmail)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Step 3: POST /integrations/drive/connect/{oid}?user_email= ───
  const runSync = useCallback(async (runOid, email) => {
    setBusy(true)
    setErr(null)
    setSyncStatus('connecting')
    try {
      await connectDrive(runOid, email)
      if (!mountedRef.current || oidRef.current !== runOid) return
      setSyncStatus('success')
      // Refresh metrics after sync
      const m = await fetchDriveMetrics(runOid, email)
      if (mountedRef.current && oidRef.current === runOid) setMetrics(m)
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) {
        setSyncStatus(null)
        setErr(isWorkspacePolicyError(e) ? WORKSPACE_POLICY_ERROR_MSG : (e?.response?.data?.detail ?? e?.message ?? 'Drive sync failed. Try again.'))
      }
    } finally {
      if (mountedRef.current && oidRef.current === runOid) setBusy(false)
    }
  }, [])

  // ── Step 2: GET /auth/google/url?provider=drive&user_email=&oid=&redirect_uri=
  const handleConnectWithEmail = useCallback(async (email) => {
    const runOid = oid
    setShowModal(false)
    setUserEmail(email)
    ssSet(SS_EMAIL(runOid), email)
    setBusy(true)
    setErr(null)
    setSyncStatus(null)
    try {
      const result = await getDriveAuthUrl(email, runOid, getDriveOAuthRedirectUri())

      if (result?.already_connected) {
        // Already connected — go straight to sync
        await runSync(runOid, email)
        return
      }

      if (result?.auth_url) {
        // Needs OAuth — save pending and redirect to Google
        ssSet(SS_PENDING_OID, runOid)
        ssSet(SS_PENDING_EMAIL, email)
        window.location.href = String(result.auth_url).trim()
        return
      }

      // Fallback: try sync anyway
      await runSync(runOid, email)
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) {
        setErr(isWorkspacePolicyError(e) ? WORKSPACE_POLICY_ERROR_MSG : (e?.response?.data?.detail ?? e?.message ?? 'Connection failed. Try again.'))
        setBusy(false)
      }
    }
  }, [oid, runSync])

  // Connect button handler — skip modal if email already stored
  const handleConnect = useCallback(() => {
    setErr(null)
    setSyncStatus(null)
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (email) { void handleConnectWithEmail(email); return }
    setShowModal(true)
  }, [oid, userEmail, handleConnectWithEmail])

  // Resync button handler — go straight to sync when we already know the
  // account; otherwise open the Connect modal so the user can re-enter
  // their Google email. The header only renders the Connect button while
  // status != ACTIVE, so without this fallback an Active-but-locally-empty
  // card (e.g. fresh browser session, cleared sessionStorage) would dead-
  // end on a "use Connect" error pointing at a button that isn't visible.
  // Re-using the modal funnels the user through getDriveAuthUrl, which
  // either short-circuits via `already_connected` straight into runSync or
  // kicks off OAuth (and the post-OAuth useEffect picks up sync on return).
  const handleResync = useCallback(() => {
    setErr(null)
    setSyncStatus(null)
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (!email) { setShowModal(true); return }
    void runSync(oid, email)
  }, [oid, userEmail, runSync])

  const totalFilesCount = Number(metrics?.total_files ?? 0)

  return (
    <>
      <style>{`
        @keyframes drSpin       { to { transform: rotate(360deg) } }
        @keyframes drPulseRing  { 0%{transform:scale(1);opacity:.6}70%{transform:scale(2.2);opacity:0}100%{transform:scale(1);opacity:0} }
        @keyframes drFadeIn     { from{opacity:0} to{opacity:1} }
        @keyframes drSlideUp    { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:none} }
        @keyframes drPulse      { 0%,100%{opacity:.45} 50%{opacity:1} }
      `}</style>

      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 22px', borderBottom: isActive ? '1px solid var(--border)' : 'none',
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: 'rgba(66,133,244,.06)', border: '1.5px solid rgba(66,133,244,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <GDriveIcon size={22} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>Google Drive</span>
            <Dot active={isActive} />
            <span style={{ fontSize: 11, color: isActive ? GREEN : '#94A3B8', fontWeight: 600 }}>
              {isActive ? 'Active' : 'Not connected'}
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Documents &amp; Files</div>
          {userEmail && (
            <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2 }}>
              <span style={{ fontWeight: 600 }}>Account: </span>
              <span style={{ color: NAVY, fontWeight: 700 }}>{userEmail}</span>
            </div>
          )}
        </div>

        {/* Connect button — status != ACTIVE */}
        {!isActive && (
          <button type="button" disabled={busy} onClick={handleConnect}
            style={{
              flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${DRIVE_BLUE}`, background: DRIVE_BLUE, color: '#fff',
              fontFamily: 'var(--font)', transition: 'opacity .12s', opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Connecting…' : 'Connect Google Drive'}
          </button>
        )}

        {/* Resync button — status == ACTIVE */}
        {isActive && (
          <button type="button" disabled={busy} onClick={handleResync}
            style={{
              flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${DRIVE_BLUE}`, background: 'rgba(66,133,244,.1)', color: DRIVE_BLUE,
              fontFamily: 'var(--font)', transition: 'opacity .12s', opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Syncing…' : 'Resync Drive'}
          </button>
        )}
      </div>

      {/* Sync status feedback */}
      {syncStatus === 'connecting' && (
        <div style={{ padding: '10px 22px 14px 80px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <SpinIcon size={12} />
          <span style={{ fontSize: 12, color: DRIVE_BLUE, fontWeight: 600 }}>Connecting project folder…</span>
        </div>
      )}
      {syncStatus === 'success' && (
        <div style={{ padding: '10px 22px 14px 80px' }}>
          <span style={{ fontSize: 12, color: '#047857', fontWeight: 700 }}>
            Drive connected successfully. Files are being synced.
          </span>
        </div>
      )}

      {/* Metrics — status == ACTIVE */}
      {isActive && metrics && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(66,133,244,.15)',
            background: 'rgba(66,133,244,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '9px 16px 8px', borderBottom: '1px solid rgba(66,133,244,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={DRIVE_BLUE} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: DRIVE_BLUE }}>
                Sync metadata
              </span>
              {metricsLoading && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 6, color: DRIVE_BLUE, opacity: .8 }}>
                  <SpinIcon size={9} />
                  <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase' }}>Refreshing</span>
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 16px 16px' }}>
              <div style={{
                flex: '1 1 120px', padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(66,133,244,.1)' : 'none',
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

      {/* Error */}
      {err && err === WORKSPACE_POLICY_ERROR_MSG && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <div style={{
            display: 'flex', gap: 10, padding: '10px 14px', borderRadius: 10,
            background: 'rgba(234,179,8,.08)', border: '1px solid rgba(234,179,8,.35)',
          }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#B45309" strokeWidth="2" strokeLinecap="round" style={{ flexShrink: 0, marginTop: 1 }}>
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <span style={{ fontSize: 12, color: '#92400E', fontWeight: 600, lineHeight: 1.5 }}>{err}</span>
          </div>
        </div>
      )}
      {err && err !== WORKSPACE_POLICY_ERROR_MSG && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, color: '#DC2626' }}>{err}</span>
        </div>
      )}

      {showModal && (
        <EmailModal oid={oid} onSubmit={handleConnectWithEmail} onCancel={() => setShowModal(false)} />
      )}
    </>
  )
}
