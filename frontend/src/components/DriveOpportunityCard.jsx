/**
 * DriveOpportunityCard
 *
 * Per-opportunity Google Drive (Gmail-style): enter Google account email, then
 * GET /integrations/drive/authorize-info/{oid}?user_email=&redirect_uri=
 * → POST /integrations/drive/connect/{oid}?user_email=
 * → GET metrics. Optional full-page OAuth via auth_url or legacy Google URL.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { toApiOpportunityId } from '../config/opportunityApi'
import { useDriveConnector } from '../hooks/useDriveConnector'
import {
  connectDrive,
  fetchDriveConnectInfo,
  fetchDriveMetrics,
  getCachedDriveConnectInfo,
  getCachedDriveMetrics,
  getDriveOAuthRedirectUri,
  getDriveSourcesReturnUrl,
  getGoogleOAuthUrl,
  getOAuthRedirectUri,
  OAUTH_RETURN_CREATE_OPP_KEY,
  OAUTH_OPP_ID_KEY,
  OAUTH_OPP_NAME_KEY,
  OAUTH_PROVIDER_KEY,
} from '../services/integrationsAuthApi'
import { traceSkip } from '../services/connectorTrace'
import { GDriveIcon } from './SourceIcons'

const IS_DEV = import.meta.env.DEV

/* ── Dev audit panel ──────────────────────────────────────────────── */
const CALL_NAMES = ['authorizeInfo', 'connect', 'metrics']
const STATUS_COLOR = { idle: '#CBD5E1', loading: '#F59E0B', success: '#10B981', error: '#DC2626', skipped: '#94A3B8' }
const STATUS_ICON  = { idle: '—', loading: '…', success: '✓', error: '✗', skipped: '⊘' }

function DevPanel({ callState }) {
  const [open, setOpen] = useState(false)
  if (!IS_DEV) return null

  const hasError = CALL_NAMES.some(k => callState[k]?.status === 'error')

  return (
    <div style={{ margin: '0 22px 10px', borderRadius: 8, border: '1px dashed rgba(66,133,244,.25)', fontSize: 11, fontFamily: 'monospace', overflow: 'hidden' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', padding: '4px 10px', cursor: 'pointer', border: 'none',
          background: hasError ? 'rgba(220,38,38,.04)' : 'rgba(66,133,244,.04)',
          display: 'flex', gap: 10, alignItems: 'center', fontFamily: 'monospace', fontSize: 11,
        }}
      >
        <span style={{ color: '#94A3B8' }}>⚙ connector audit</span>
        {CALL_NAMES.map(k => {
          const s = callState[k]?.status ?? 'idle'
          return (
            <span key={k} title={k} style={{ color: STATUS_COLOR[s] ?? '#CBD5E1', fontWeight: 700 }}>
              {k.slice(0, 4)}:{STATUS_ICON[s] ?? s}
            </span>
          )
        })}
        <span style={{ marginLeft: 'auto', color: '#94A3B8' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ padding: '8px 10px', background: '#FAFCFF', borderTop: '1px dashed rgba(66,133,244,.15)' }}>
          {CALL_NAMES.map(k => {
            const s = callState[k] ?? { status: 'idle' }
            return (
              <div key={k} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <span style={{ color: '#64748B', minWidth: 88 }}>{k}</span>
                  <span style={{ fontWeight: 700, color: STATUS_COLOR[s.status] ?? '#CBD5E1' }}>
                    {s.status}
                  </span>
                  {s.ts && (
                    <span style={{ color: '#94A3B8', fontSize: 10 }}>
                      {new Date(s.ts).toLocaleTimeString()}
                    </span>
                  )}
                  {s.ms != null && <span style={{ color: '#94A3B8', fontSize: 10 }}>{s.ms}ms</span>}
                </div>
                {s.status === 'error' && s.error != null && (
                  <div style={{ color: '#DC2626', fontSize: 10, marginTop: 2, paddingLeft: 96, wordBreak: 'break-all' }}>
                    {s.error.httpStatus ? `HTTP ${s.error.httpStatus}: ` : ''}
                    {JSON.stringify(s.error.detail ?? s.error).slice(0, 200)}
                  </div>
                )}
                {s.status === 'skipped' && s.reason && (
                  <div style={{ color: '#94A3B8', fontSize: 10, marginTop: 2, paddingLeft: 96 }}>
                    skip: {s.reason}
                  </div>
                )}
                {s.status === 'success' && s.response != null && (
                  <div style={{ color: '#047857', fontSize: 10, marginTop: 2, paddingLeft: 96, wordBreak: 'break-all' }}>
                    {JSON.stringify(s.response).slice(0, 200)}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const DRIVE_BLUE = '#4285F4'
const NAVY = '#1B264F'
const GREEN = '#10B981'

function timeAgo(iso) {
  if (!iso) return null
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

/** Connect-info may omit has_drive_connection; trust status ACTIVE. */
function isDriveActiveFromConnectInfo(info) {
  if (!info) return false
  const st = String(info.status ?? '').toUpperCase()
  if (st === 'ACTIVE') return true
  if (info.has_drive_connection === true) return true
  return false
}

function mapDriveError(e) {
  const status = e?.response?.status
  const detail = String(e?.response?.data?.detail ?? e?.message ?? '').toLowerCase()
  if (status === 404 && detail.includes('oid')) return 'OID not found in Drive connector.'
  if (detail.includes('token') && detail.includes('missing')) return 'Drive connector token is missing. Please reconnect the shared connector account.'
  if (detail.includes('root folder') && detail.includes('missing')) return 'Drive root folder is missing. Verify connector folder configuration.'
  if (detail.includes('no discoverable') || detail.includes('no oid folders')) return 'No discoverable OID folders were found.'
  return e?.response?.data?.detail ?? e?.message ?? 'Drive request failed.'
}


/* ── helpers ──────────────────────────────────────────────────────── */
function SpinIcon({ size = 13 }) {
  return (
    <svg style={{ animation: 'driveOppSpin .9s linear infinite', flexShrink: 0 }}
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
  )
}

function Dot({ active }) {
  const c = active ? GREEN : '#CBD5E1'
  return (
    <span style={{ position: 'relative', width: 8, height: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      {active && (
        <span style={{
          position: 'absolute', width: 8, height: 8, borderRadius: '50%',
          background: c, animation: 'driveOppPulseRing 1.6s ease-out infinite',
        }} />
      )}
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, position: 'relative' }} />
    </span>
  )
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function pickConnectorUserEmail(info) {
  if (!info || typeof info !== 'object') return ''
  const v = info.connector_user_email ?? info.user_email ?? info.userEmail ?? info.mailbox ?? info.email
  return typeof v === 'string' ? v.trim().toLowerCase() : ''
}

/** Enter Google account email for this opportunity (same UX pattern as Gmail). */
function DriveConnectModal({ initialEmail, oid, onSubmit, onCancel }) {
  const [value, setValue] = useState(initialEmail || '')
  const [localErr, setLocalErr] = useState('')

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  const submit = () => {
    const t = value.trim()
    if (!t) {
      setLocalErr('Enter a Google account email.')
      return
    }
    if (!EMAIL_RE.test(t)) {
      setLocalErr('Enter a valid email address.')
      return
    }
    setLocalErr('')
    onSubmit(t.toLowerCase())
  }

  return createPortal(
    <div
      onClick={onCancel}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(15,23,42,.55)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24, animation: 'driveOppFadeIn .15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 420, background: 'var(--bg2, #fff)', borderRadius: 16,
          boxShadow: '0 24px 64px rgba(15,23,42,.22)', overflow: 'hidden',
          animation: 'driveOppSlideUp .18s ease', fontFamily: 'var(--font)',
        }}
      >
        <div style={{ padding: '20px 24px 12px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 800, color: NAVY }}>Connect Drive for this project</h3>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--text2)', lineHeight: 1.55 }}>
            Enter the Google account that can access the Drive folder for project{' '}
            <strong style={{ color: NAVY }}>{oid}</strong>. This email is used for authorize-info and connect (user-scoped mode).
          </p>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: NAVY, marginBottom: 6 }}>Google account email</label>
          <input
            type="email"
            autoComplete="email"
            value={value}
            onChange={e => { setValue(e.target.value); setLocalErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="you@company.com"
            style={{
              width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: 10,
              border: `1.5px solid ${localErr ? '#DC2626' : 'rgba(27,38,79,.15)'}`,
              fontSize: 13, fontFamily: 'var(--font)', outline: 'none',
            }}
          />
          {localErr && (
            <p style={{ margin: '8px 0 0', fontSize: 11, color: '#DC2626', fontWeight: 600 }}>{localErr}</p>
          )}
          <p style={{
            margin: '14px 0 0', fontSize: 12.5, color: 'var(--text2)', lineHeight: 1.65,
            padding: '12px 14px', borderRadius: 10,
            background: 'rgba(66,133,244,.04)', border: '1px solid rgba(66,133,244,.15)',
          }}>
            This allows Knowledge Assist to read documents from the Drive folder mapped to this opportunity.
          </p>
        </div>
        <div style={{ padding: '0 24px 20px', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            type="button" onClick={onCancel}
            style={{
              padding: '8px 18px', borderRadius: 8, border: '1.5px solid rgba(27,38,79,.15)',
              background: 'transparent', color: 'var(--text2)', fontSize: 12, fontWeight: 600,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}
          >Cancel</button>
          <button
            type="button" onClick={submit}
            style={{
              padding: '8px 20px', borderRadius: 8, border: `1.5px solid ${DRIVE_BLUE}`,
              background: DRIVE_BLUE, color: '#fff', fontSize: 12, fontWeight: 700,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}
          >Connect</button>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ── DriveOpportunityCard ─────────────────────────────────────────── */
export default function DriveOpportunityCard({ opportunityId, opportunityName, onStatusChange }) {
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])
  const driveIdentity = useDriveConnector(oid)

  const [connectInfo, setConnectInfo] = useState(() => getCachedDriveConnectInfo(oid))
  const [active,     setActive]     = useState(() => isDriveActiveFromConnectInfo(getCachedDriveConnectInfo(oid)))
  const [metrics,    setMetrics]    = useState(() => {
    const ci = getCachedDriveConnectInfo(oid)
    if (!isDriveActiveFromConnectInfo(ci)) return null
    return getCachedDriveMetrics(oid) ?? null
  })
  const [metricsLoading, setMetricsLoading] = useState(() => {
    const ci = getCachedDriveConnectInfo(oid)
    return isDriveActiveFromConnectInfo(ci) && !getCachedDriveMetrics(oid)
  })
  const [busy,       setBusy]       = useState(false)
  const [connectModal, setConnectModal] = useState(false)
  const [err,        setErr]        = useState(null)
  const [toast,      setToast]      = useState(null)

  /** Per-call audit state rendered in the dev panel. */
  const [callState, setCallState] = useState({
    authorizeInfo: { status: 'idle' },
    connect:       { status: 'idle' },
    metrics:       { status: 'idle' },
  })
  /** Update a single call entry. status: 'loading'|'success'|'error'|'skipped' */
  const stamp = useCallback((name, status, extra = {}) =>
    setCallState(prev => ({ ...prev, [name]: { status, ts: Date.now(), ...extra } })),
  [])

  const mountedRef   = useRef(true)
  /** Viewed opportunity; connect/resync for `runOid` may finish after navigation — API/cache still update. */
  const oidRef = useRef(oid)
  oidRef.current = oid
  /** Latches connected state so transient API failures do not regress UI to disconnected. */
  const connectedRef = useRef(isDriveActiveFromConnectInfo(getCachedDriveConnectInfo(oid)))
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    setConnectInfo(getCachedDriveConnectInfo(oid))
    setErr(null)
    setBusy(false)
    setConnectModal(false)
    const ci = getCachedDriveConnectInfo(oid)
    const activeNow = isDriveActiveFromConnectInfo(ci)
    setActive(activeNow)
    const m = activeNow ? (getCachedDriveMetrics(oid) ?? null) : null
    setMetrics(m)
    setMetricsLoading(activeNow && !m)
    connectedRef.current = isDriveActiveFromConnectInfo(ci)
  }, [oid])

  useEffect(() => {
    const ci = getCachedDriveConnectInfo(oid)
    if (!isDriveActiveFromConnectInfo(ci) || driveIdentity.identity?.userEmail) return
    const hint = pickConnectorUserEmail(ci)
    if (hint) driveIdentity.setIdentity(hint)
  }, [oid, connectInfo?.connector_user_email, connectInfo?.status, driveIdentity.identity?.userEmail, driveIdentity.setIdentity])

  /** Seed metrics from connect / authorize-info payload when GET metrics is slow. */
  function seedMetricsFromInfo(info) {
    return {
      total_files:    info?.total_files    ?? info?.files_uploaded ?? info?.file_count   ?? null,
      last_synced_at: info?.last_synced_at ?? info?.last_sync_at ?? null,
      oid:            info?.oid ?? null,
      status:         info?.status ?? null,
    }
  }

  /** Dev: no auto network calls until the user submits an email (same idea as Gmail card). */
  useEffect(() => {
    if (!oid) {
      traceSkip('fetchDriveConnectInfo', 'oid is falsy')
      stamp('authorizeInfo', 'skipped', { reason: 'oid is falsy' })
      return
    }
    traceSkip('fetchDriveConnectInfo', 'manual connect until user submits email')
    stamp('authorizeInfo', 'skipped', { reason: 'manual connect until email' })
    stamp('metrics', 'skipped', { reason: 'manual connect until email' })
  }, [oid, stamp])

  const resolveMailbox = useCallback(() => {
    const id = driveIdentity.identity?.userEmail?.trim().toLowerCase()
    if (id) return id
    return pickConnectorUserEmail(connectInfo) || pickConnectorUserEmail(getCachedDriveConnectInfo(oid))
  }, [connectInfo, driveIdentity.identity?.userEmail, oid])

  const loadMetrics = useCallback(async (seedInfo = null, ctx = null) => {
    const metricsOid = ctx?.runOid ?? oid
    const mailboxFromCtx = typeof ctx?.mailbox === 'string' ? ctx.mailbox.trim().toLowerCase() : ''
    if (!metricsOid) {
      traceSkip('fetchDriveMetrics', 'oid is falsy')
      stamp('metrics', 'skipped', { reason: 'oid is falsy' })
      return
    }
    const mailbox = (mailboxFromCtx || resolveMailbox()) || undefined
    if (mountedRef.current && oidRef.current === metricsOid) {
      if (seedInfo) setMetrics(prev => prev ?? seedMetricsFromInfo(seedInfo))
      setMetricsLoading(true)
    }
    stamp('metrics', 'loading')
    const t0 = performance.now()
    try {
      const m = await fetchDriveMetrics(metricsOid, mailbox)
      if (mountedRef.current && oidRef.current === metricsOid) {
        stamp('metrics', 'success', { response: m, ms: Math.round(performance.now() - t0) })
        connectedRef.current = true
        setMetrics(m)
        setActive(true)
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === metricsOid) {
        stamp('metrics', 'error', { error: { httpStatus: e?.response?.status, detail: e?.response?.data ?? e?.message }, ms: Math.round(performance.now() - t0) })
        setErr(mapDriveError(e))
      }
    } finally {
      if (mountedRef.current && oidRef.current === metricsOid) setMetricsLoading(false)
    }
  }, [oid, stamp, resolveMailbox])

  /* ── OAuth redirect helper (legacy frontend Google URL) ── */
  const redirectToOAuth = useCallback(async () => {
    try {
      const redirectUri = getOAuthRedirectUri()
      sessionStorage.setItem(OAUTH_RETURN_CREATE_OPP_KEY, 'sources')
      if (oid) sessionStorage.setItem(OAUTH_OPP_ID_KEY, oid)
      if (opportunityName) sessionStorage.setItem(OAUTH_OPP_NAME_KEY, opportunityName)
      sessionStorage.setItem(OAUTH_PROVIDER_KEY, 'google')
      const { auth_url } = await getGoogleOAuthUrl(redirectUri)
      window.location.href = auth_url
    } catch (oauthErr) {
      if (mountedRef.current)
        setErr(oauthErr?.message ?? 'Failed to start Google authorization.')
    }
  }, [oid, opportunityName])

  const runDriveConnectPipeline = useCallback(async (email) => {
    const runOid = oid
    driveIdentity.setIdentity(email)
    setConnectModal(false)
    setBusy(true)
    setErr(null)
    const redirectUri = getDriveOAuthRedirectUri()
    try {
      if (!runOid) {
        stamp('authorizeInfo', 'skipped', { reason: 'oid is falsy' })
        return
      }

      stamp('authorizeInfo', 'loading')
      const t0 = performance.now()
      let info
      try {
        info = await fetchDriveConnectInfo(runOid, { userEmail: email, redirectUri, returnUrl: getDriveSourcesReturnUrl(runOid) })
        stamp('authorizeInfo', 'success', { response: info, ms: Math.round(performance.now() - t0) })
        if (mountedRef.current && oidRef.current === runOid) setConnectInfo(prev => ({ ...(prev || {}), ...info }))
      } catch (e) {
        stamp('authorizeInfo', 'error', { error: { httpStatus: e?.response?.status, detail: e?.response?.data ?? e?.message }, ms: Math.round(performance.now() - t0) })
        if (mountedRef.current && oidRef.current === runOid) setErr(mapDriveError(e))
        return
      }

      if (info?.auth_url && String(info.auth_url).trim()) {
        window.location.href = String(info.auth_url).trim()
        return
      }

      stamp('connect', 'loading')
      const t1 = performance.now()
      let conn
      try {
        conn = await connectDrive(runOid, email)
        stamp('connect', 'success', { response: conn, ms: Math.round(performance.now() - t1) })
        if (mountedRef.current && oidRef.current === runOid) setConnectInfo(prev => ({ ...(prev || {}), ...conn }))
      } catch (e) {
        stamp('connect', 'error', { error: { httpStatus: e?.response?.status, detail: e?.response?.data ?? e?.message }, ms: Math.round(performance.now() - t1) })
        const status = e?.response?.status
        const detail = String(e?.response?.data?.detail ?? e?.message ?? '').toLowerCase()
        const needsOAuth =
          e?.response?.data?.requires_oauth === true ||
          (status === 401 && (detail.includes('oauth') || detail.includes('token')))
        if (needsOAuth) {
          stamp('metrics', 'skipped', { reason: 'OAuth required after connect' })
          await redirectToOAuth()
          return
        }
        if (mountedRef.current && oidRef.current === runOid) setErr(mapDriveError(e))
        return
      }

      if (conn?.auth_url && String(conn.auth_url).trim()) {
        window.location.href = String(conn.auth_url).trim()
        return
      }

      if (oidRef.current !== runOid) {
        traceSkip('fetchDriveMetrics', 'opportunity changed before metrics step')
        return
      }
      connectedRef.current = true
      setActive(true)
      onStatusChange?.(true)
      setToast('Drive connected')
      await loadMetrics(conn, { runOid, mailbox: email })
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) setErr(mapDriveError(e))
    } finally {
      if (mountedRef.current && oidRef.current === runOid) setBusy(false)
    }
  }, [oid, driveIdentity.setIdentity, stamp, redirectToOAuth, loadMetrics, onStatusChange])

  const handleResync = useCallback(async () => {
    const runOid = oid
    const email = resolveMailbox()
    if (!email) {
      setErr('Enter your Google account via Connect for this opportunity first.')
      return
    }
    setBusy(true)
    setErr(null)
    const redirectUri = getDriveOAuthRedirectUri()
    try {
      const info = await fetchDriveConnectInfo(runOid, { userEmail: email, redirectUri, returnUrl: getDriveSourcesReturnUrl(runOid) })
      if (info?.auth_url && String(info.auth_url).trim()) {
        window.location.href = String(info.auth_url).trim()
        return
      }
      const conn = await connectDrive(runOid, email)
      if (!mountedRef.current || oidRef.current !== runOid) return
      setConnectInfo(prev => ({ ...(prev || {}), ...conn }))
      connectedRef.current = true
      setActive(true)
      const m = await fetchDriveMetrics(runOid, email)
      if (!mountedRef.current || oidRef.current !== runOid) return
      setMetrics(m)
      onStatusChange?.(true)
      setToast('Drive resynced')
    } catch (e) {
      const status = e?.response?.status
      const detail = String(e?.response?.data?.detail ?? e?.message ?? '').toLowerCase()
      const needsOAuth =
        e?.response?.data?.requires_oauth === true ||
        (status === 401 && (detail.includes('oauth') || detail.includes('token')))
      if (needsOAuth && mountedRef.current && oidRef.current === runOid) {
        await redirectToOAuth()
        return
      }
      if (mountedRef.current && oidRef.current === runOid) setErr(mapDriveError(e))
    } finally {
      if (mountedRef.current && oidRef.current === runOid) setBusy(false)
    }
  }, [oid, onStatusChange, redirectToOAuth, resolveMailbox])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2400)
    return () => clearTimeout(t)
  }, [toast])

  const rawStatus = String(connectInfo?.status ?? metrics?.status ?? '').toUpperCase()
  const displayActive = active || rawStatus === 'ACTIVE'
  const statusText    = rawStatus || (displayActive ? 'ACTIVE' : 'NOT CONNECTED')
  const statusColor   = displayActive ? GREEN : '#94A3B8'
  const showMetrics   = Boolean(metrics) && !metricsLoading
  const masterFolderUrl = connectInfo?.master_folder_url || import.meta.env.VITE_DRIVE_MASTER_FOLDER_URL
  const totalFilesCount = Number(metrics?.total_files ?? 0)

  useEffect(() => {
    onStatusChange?.(displayActive)
  }, [displayActive, onStatusChange])

  return (
    <>
      <style>{`
        @keyframes driveOppSpin       { to { transform: rotate(360deg) } }
        @keyframes driveOppPulseRing  { 0% { transform: scale(1); opacity: .6; } 70% { transform: scale(2.2); opacity: 0; } 100% { transform: scale(1); opacity: 0; } }
        @keyframes driveOppFadeIn     { from { opacity: 0 } to { opacity: 1 } }
        @keyframes driveOppSlideUp    { from { opacity: 0; transform: translateY(10px) } to { opacity: 1; transform: none } }
        @keyframes driveOppPulse      { 0%, 100% { opacity: .45 } 50% { opacity: 1 } }
      `}</style>

      {/* ── Card header row ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 22px', borderBottom: displayActive ? '1px solid var(--border)' : 'none',
      }}>
        {/* Icon */}
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: 'rgba(66,133,244,.06)', border: '1.5px solid rgba(66,133,244,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <GDriveIcon size={22} />
        </div>

        {/* Title + status */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>Google Drive</span>
            <Dot active={displayActive} />
            <span style={{
              fontSize: 10, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
              padding: '3px 8px', borderRadius: 10,
              color: statusColor,
              background: displayActive ? 'rgba(16,185,129,.12)' : 'rgba(100,116,139,.12)',
              border: `1px solid ${displayActive ? 'rgba(16,185,129,.25)' : 'rgba(100,116,139,.2)'}`,
            }}>{statusText}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Documents &amp; Files</div>
          {driveIdentity.identity?.userEmail && (
            <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2 }}>
              <span style={{ fontWeight: 600 }}>Google account (this project): </span>
              <span style={{ color: 'var(--text1)', fontWeight: 700 }}>{driveIdentity.identity.userEmail}</span>
            </div>
          )}
          {!driveIdentity.identity?.userEmail && (
            <div style={{ fontSize: 10.5, color: '#94A3B8', marginTop: 2 }}>
              Not connected — click Connect and enter the Google account that can access this opportunity&apos;s Drive folder.
            </div>
          )}
        </div>

        {/* Connect button — shown until active */}
        {!displayActive && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); setConnectModal(true) }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${DRIVE_BLUE}`,
              background: DRIVE_BLUE, color: '#fff',
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Connecting…' : 'Connect Drive'}
          </button>
        )}
        {displayActive && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); void handleResync() }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${DRIVE_BLUE}`,
              background: 'rgba(66,133,244,.1)', color: DRIVE_BLUE,
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Resyncing…' : 'Resync'}
          </button>
        )}
      </div>

      {/* ── Metrics loading skeleton ── */}
      {displayActive && metricsLoading && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(66,133,244,.12)',
            background: 'rgba(66,133,244,.02)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <SpinIcon size={12} style={{ color: DRIVE_BLUE }} />
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: DRIVE_BLUE }}>
                Loading metrics…
              </span>
            </div>
            {[90, 60].map((w, i) => (
              <div key={i} style={{
                height: 10, borderRadius: 5, marginBottom: 6,
                width: `${w}%`, background: 'rgba(66,133,244,.1)',
                animation: 'driveOppPulse 1.4s ease-in-out infinite',
                animationDelay: `${i * 0.15}s`,
              }} />
            ))}
          </div>
        </div>
      )}

      {/* ── Metrics: raw GET metrics response ── */}
      {showMetrics && !metricsLoading && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(66,133,244,.15)',
            background: 'rgba(66,133,244,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '8px 14px', borderBottom: '1px solid rgba(66,133,244,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={DRIVE_BLUE} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: DRIVE_BLUE }}>
                Sync metadata
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 14px 16px' }}>
              <div style={{
                flex: '1 1 120px',
                padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(66,133,244,.1)' : 'none',
              }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>Total files</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 22, fontWeight: 800, color: NAVY, lineHeight: 1 }}>{totalFilesCount}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--text2)' }}>
                    {totalFilesCount === 1 ? 'file' : 'files'}
                  </span>
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

      {/* ── Active but metrics not yet loaded ── */}
      {displayActive && !metricsLoading && !showMetrics && (
        <div style={{ padding: '10px 22px 14px 80px' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text2)', fontWeight: 600 }}>
            Connected — metrics not available yet.
          </span>
        </div>
      )}

      {/* ── Master folder link ── */}
      {masterFolderUrl && (
        <div style={{ padding: showMetrics ? '0 22px 14px 80px' : '10px 22px 14px 80px' }}>
          <a
            href={masterFolderUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 10px', borderRadius: 8,
              border: '1px solid rgba(66,133,244,.3)',
              background: 'rgba(66,133,244,.05)',
              color: DRIVE_BLUE, fontSize: 11.5, fontWeight: 700,
              textDecoration: 'none', transition: 'background .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(66,133,244,.1)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(66,133,244,.05)' }}
          >
            <GDriveIcon size={12} />
            Open Master Folder
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
          </a>
        </div>
      )}

      {/* ── Error ── */}
      {err && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, color: '#DC2626' }}>{err}</span>
        </div>
      )}
      {toast && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, color: '#047857', fontWeight: 700 }}>{toast}</span>
        </div>
      )}

      {/* ── Dev audit panel (dev only) ── */}
      <DevPanel callState={callState} />

      {connectModal && (
        <DriveConnectModal
          oid={oid}
          initialEmail={driveIdentity.identity?.userEmail ?? ''}
          onSubmit={runDriveConnectPipeline}
          onCancel={() => setConnectModal(false)}
        />
      )}
    </>
  )
}
