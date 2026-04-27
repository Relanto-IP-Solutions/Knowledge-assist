/**
 * GmailOpportunityCard — per-opportunity Gmail on the Sources page only.
 * After mailbox input: **discover(oid + user_email) → connect(oid) → GET metrics(oid)** (see runGmailOpportunityConnectSequence).
 * Resync: connect(oid) + metrics only.
 * All API paths use `toApiOpportunityId(opportunityId)` as the backend **oid**.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import {
  useGmailConnector,
  GMAIL_SELECTED_OID_SESSION_KEY,
  GMAIL_CONNECTOR_EMAIL_SESSION_KEY,
  gmailConnectorEmailSessionKey,
} from '../hooks/useGmailConnector'
import { toApiOpportunityId } from '../config/opportunityApi'
import { mapGmailError, WORKSPACE_POLICY_ERROR_MSG } from '../utils/gmailErrorMapper'
import {
  connectGmail,
  fetchGmailConnectInfo,
  fetchGmailMetrics,
  getCachedGmailConnectInfo,
  getCachedGmailMetrics,
  getGmailBackendRedirectUri,
  getGmailSourcesReturnUrl,
  runGmailOpportunityConnectSequence,
} from '../services/integrationsAuthApi'
import { GmailIcon } from './SourceIcons'

const GMAIL_RED = '#EA4335'
const NAVY = '#1B264F'
const GREEN = '#10B981'

function timeAgo(iso) {
  if (!iso) return null
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function metricsFromConnectPayload(result) {
  if (!result || typeof result !== 'object') return null
  const m = result.metrics ?? result.gmail_metrics
  if (m && typeof m === 'object') return m
  const keys = [
    'total_threads', 'thread_count', 'threads_for_requested_mailbox',
    'raw_files', 'processed_files', 'last_synced_at',
  ]
  const out = {}
  let any = false
  for (const k of keys) {
    if (result[k] !== undefined) {
      out[k] = result[k]
      any = true
    }
  }
  return any ? out : null
}

function SpinIcon({ size = 13 }) {
  return (
    <svg style={{ animation: 'gmailOppSpin .9s linear infinite', flexShrink: 0 }}
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
          background: c, animation: 'gmailOppPulseRing 1.6s ease-out infinite',
        }} />
      )}
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, position: 'relative' }} />
    </span>
  )
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function pickMailboxFromConnectInfo(info) {
  if (!info || typeof info !== 'object') return ''
  const v = info.user_email ?? info.userEmail ?? info.mailbox ?? info.email
    ?? info.connected_mailbox ?? info.gmail_user ?? info.connected_user_email
  return typeof v === 'string' ? v.trim().toLowerCase() : ''
}

function readScopedMailboxSession(oid) {
  try {
    const s = sessionStorage.getItem(gmailConnectorEmailSessionKey(oid))
    if (s && EMAIL_RE.test(s)) return s.trim().toLowerCase()
  } catch { /**/ }
  return ''
}

/** Enter Gmail for this opportunity, then confirm — opens from Connect */
function GmailConnectModal({ initialEmail, onSubmit, onCancel }) {
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
      setLocalErr('Enter a Gmail address.')
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
        padding: 24, animation: 'gmailOppFadeIn .15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 420, background: 'var(--bg2, #fff)', borderRadius: 16,
          boxShadow: '0 24px 64px rgba(15,23,42,.22)', overflow: 'hidden',
          animation: 'gmailOppSlideUp .18s ease', fontFamily: 'var(--font)',
        }}
      >
        <div style={{ padding: '20px 24px 12px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 800, color: NAVY }}>Connect Gmail for this project</h3>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--text2)', lineHeight: 1.55 }}>
            Enter the Google mailbox to scan for threads that match this opportunity.
          </p>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: NAVY, marginBottom: 6 }}>Gmail address</label>
          <input
            type="email"
            autoComplete="email"
            value={value}
            onChange={e => { setValue(e.target.value); setLocalErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') submit() }}
            placeholder="example@company.com"
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
            background: 'rgba(234,67,53,.04)', border: '1px solid rgba(234,67,53,.15)',
          }}>
            This allows Knowledge Assist to read Gmail threads related to this opportunity.
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
              padding: '8px 20px', borderRadius: 8, border: `1.5px solid ${GMAIL_RED}`,
              background: GMAIL_RED, color: '#fff', fontSize: 12, fontWeight: 700,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}
          >Connect</button>
        </div>
      </div>
    </div>,
    document.body
  )
}

export default function GmailOpportunityCard({ opportunityId, onStatusChange }) {
  /** Single backend id for discover / connect / metrics / scoped identity */
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])
  const hook = useGmailConnector(oid)

  const [connectInfo, setConnectInfo] = useState(() => getCachedGmailConnectInfo(oid))
  const [metrics,     setMetrics]     = useState(() => {
    const ci = getCachedGmailConnectInfo(oid)
    if (ci?.status !== 'ACTIVE') return null
    return getCachedGmailMetrics(oid) ?? null
  })
  const [resolving]      = useState(false)
  const [metricsLoading, setMetricsLoading] = useState(() => {
    const ci = getCachedGmailConnectInfo(oid)
    return ci?.status === 'ACTIVE' && !getCachedGmailMetrics(oid)
  })
  const [busy,           setBusy]           = useState(false)
  const [connectModal,    setConnectModal]  = useState(false)
  const [err,             setErr]           = useState(null)
  const [awaitingOAuth, setAwaitingOAuth] = useState(false)
  const awaitingOAuthRef = useRef(false)

  const oauthPopupRef = useRef(null)
  const mountedRef = useRef(true)
  /** Viewed opportunity; connect/resync for `runOid` may finish after navigation — API cache still updates. */
  const oidRef = useRef(oid)
  oidRef.current = oid

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  /** When switching opportunity id, re-read cached connect state (avoids stale card state). */
  useEffect(() => {
    setConnectInfo(getCachedGmailConnectInfo(oid))
    setErr(null)
    setBusy(false)
    setConnectModal(false)
    awaitingOAuthRef.current = false
    setAwaitingOAuth(false)
    const ci = getCachedGmailConnectInfo(oid)
    if (ci?.status !== 'ACTIVE') {
      setMetrics(null)
      setMetricsLoading(false)
      return
    }
    const hint = readScopedMailboxSession(oid)
    const cachedM = hint
      ? (getCachedGmailMetrics(oid, hint) ?? getCachedGmailMetrics(oid))
      : getCachedGmailMetrics(oid)
    setMetrics(cachedM ?? null)
    setMetricsLoading(!cachedM)
  }, [oid])

  /** ACTIVE in cache but localStorage identity missing (refresh / return from OAuth) — restore mailbox for metrics + resync. */
  useEffect(() => {
    let alive = true
    async function hydrate() {
      const ci = getCachedGmailConnectInfo(oid)
      if (ci?.status !== 'ACTIVE') return
      if (hook.identity?.userEmail) return
      const scoped = readScopedMailboxSession(oid)
      if (scoped) {
        hook.setIdentity(scoped)
        return
      }
      try {
        const info = await fetchGmailConnectInfo(oid)
        if (!alive) return
        setConnectInfo(prev => ({ ...(prev || {}), ...info }))
        const mbox = pickMailboxFromConnectInfo(info)
        if (mbox) hook.setIdentity(mbox)
      } catch { /**/ }
    }
    void hydrate()
    return () => { alive = false }
  }, [oid, hook.identity?.userEmail, hook.setIdentity])

  /**
   * Per-oid session cache (see integrationsAuthApi Gmail metrics Maps + sessionStorage):
   * if metrics already exist for this mailbox, show them without a loading fetch on revisit.
   */
  useEffect(() => {
    let alive = true
    async function load() {
      const cachedInfo = getCachedGmailConnectInfo(oid)
      if (cachedInfo?.status !== 'ACTIVE') return
      const mailbox = hook.identity?.userEmail ?? readScopedMailboxSession(oid) ?? undefined
      const cachedM = mailbox
        ? (getCachedGmailMetrics(oid, mailbox) ?? getCachedGmailMetrics(oid))
        : getCachedGmailMetrics(oid)
      if (cachedM && typeof cachedM === 'object') {
        if (alive) {
          setMetrics(cachedM)
          setMetricsLoading(false)
        }
        return
      }
      try {
        if (alive) setMetricsLoading(true)
        const m = await fetchGmailMetrics(oid, mailbox)
        if (alive) setMetrics(m)
      } catch {
        if (alive) setMetrics(null)
      } finally {
        if (alive) setMetricsLoading(false)
      }
    }
    void load()
    return () => { alive = false }
  }, [oid, hook.identity?.userEmail])

  useEffect(() => {
    const handler = (event) => {
      if (event.origin !== window.location.origin) return
      const msg = event.data
      if (!msg || msg.type !== 'gmail_oauth_result') return
      if (String(msg.oid) !== String(oid)) return

      awaitingOAuthRef.current = false
      setAwaitingOAuth(false)
      setBusy(false)

      if (!msg.success) {
        setErr(mapGmailError({ message: msg.error || 'Gmail authorisation failed.' }))
        return
      }

      if (msg.connectResult) {
        setConnectInfo(prev => ({
          ...(prev || {}),
          ...(msg.connectResult),
          status: msg.connectResult.status ?? 'ACTIVE',
          requires_oauth: false,
        }))
      }
      if (msg.metrics) {
        setMetrics(msg.metrics)
      }
      onStatusChange?.(true)
    }

    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [oid, onStatusChange])

  useEffect(() => {
    if (!awaitingOAuth) return
    const interval = setInterval(() => {
      if (oauthPopupRef.current && oauthPopupRef.current.closed) {
        oauthPopupRef.current = null
        awaitingOAuthRef.current = false
        setAwaitingOAuth(false)
        setBusy(false)
      }
    }, 800)
    return () => clearInterval(interval)
  }, [awaitingOAuth])

  const isActive = connectInfo?.status === 'ACTIVE'

  useEffect(() => {
    onStatusChange?.(isActive)
  }, [isActive, onStatusChange])

  const runConnectPipeline = useCallback(async (email) => {
    const runOid = oid
    hook.setIdentity(email)
    setConnectModal(false)
    setBusy(true)
    setErr(null)
    try {
      const out = await runGmailOpportunityConnectSequence(runOid, email)

      if (out.step === 'oauth_after_discover' || out.step === 'oauth_after_connect') {
        try {
          sessionStorage.setItem(GMAIL_SELECTED_OID_SESSION_KEY, String(runOid))
        } catch { /**/ }
        oauthPopupRef.current = window.open(out.auth_url, '_blank', 'noreferrer')
        awaitingOAuthRef.current = true
        setAwaitingOAuth(true)
        return
      }

      if (out.step === 'complete') {
        const { connectResult, metrics } = out
        if (mountedRef.current && oidRef.current === runOid) {
          setConnectInfo(prev => ({
            ...(prev || {}),
            ...connectResult,
            status: connectResult?.status ?? 'ACTIVE',
            requires_oauth: false,
          }))
          onStatusChange?.(true)
        }
        const inline = metricsFromConnectPayload(connectResult)
        if (inline && mountedRef.current && oidRef.current === runOid) setMetrics(inline)
        if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(true)
        try {
          if (metrics && mountedRef.current && oidRef.current === runOid) {
            setMetrics(metrics)
          } else {
            const m = await fetchGmailMetrics(runOid, email)
            if (mountedRef.current && oidRef.current === runOid) setMetrics(m)
          }
        } catch { /* keep inline */ } finally {
          if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(false)
        }
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) setErr(mapGmailError(e))
    } finally {
      if (mountedRef.current && oidRef.current === runOid) {
        if (!awaitingOAuthRef.current) setBusy(false)
      }
    }
  }, [oid, hook.setIdentity, onStatusChange])

  const resolveMailboxForResync = useCallback(async () => {
    let email = hook.identity?.userEmail?.trim().toLowerCase()
    if (email) {
      hook.setIdentity(email)
      return email
    }

    email = readScopedMailboxSession(oid)
    if (email) {
      hook.setIdentity(email)
      return email
    }

    email = pickMailboxFromConnectInfo(connectInfo)
      || pickMailboxFromConnectInfo(getCachedGmailConnectInfo(oid))
    if (email) {
      hook.setIdentity(email)
      return email
    }

    try {
      const info = await fetchGmailConnectInfo(oid)
      if (mountedRef.current) {
        setConnectInfo(prev => ({ ...(prev || {}), ...info }))
      }
      email = pickMailboxFromConnectInfo(info)
      if (email) {
        hook.setIdentity(email)
        return email
      }
    } catch { /**/ }

    try {
      const legacy = sessionStorage.getItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY)
      if (legacy && EMAIL_RE.test(legacy)) {
        email = legacy.trim().toLowerCase()
        hook.setIdentity(email)
        return email
      }
    } catch { /**/ }

    return ''
  }, [connectInfo, hook.identity?.userEmail, hook.setIdentity, oid])

  const handleResync = useCallback(async () => {
    const runOid = oid
    setBusy(true)
    setErr(null)
    try {
      const email = await resolveMailboxForResync()
      if (!email) {
        if (mountedRef.current && oidRef.current === runOid) {
          setErr('Enter Gmail via Connect for this opportunity first.')
        }
        return
      }

      const result = await connectGmail(
        runOid,
        getGmailBackendRedirectUri(),
        email,
        getGmailSourcesReturnUrl(runOid),
      )
      if (result?.requires_oauth && result?.auth_url) {
        try {
          sessionStorage.setItem(GMAIL_SELECTED_OID_SESSION_KEY, String(runOid))
        } catch { /**/ }
        oauthPopupRef.current = window.open(result.auth_url, '_blank', 'noreferrer')
        awaitingOAuthRef.current = true
        setAwaitingOAuth(true)
        return
      }

      if (mountedRef.current && oidRef.current === runOid && result) {
        setConnectInfo(prev => ({
          ...(prev || {}),
          ...result,
          status: result?.status ?? 'ACTIVE',
          requires_oauth: false,
        }))
      }
      const inline = metricsFromConnectPayload(result)
      if (inline && mountedRef.current && oidRef.current === runOid) setMetrics(inline)
      if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(true)
      try {
        const m = await fetchGmailMetrics(runOid, email)
        if (mountedRef.current && oidRef.current === runOid) {
          setMetrics(m)
          onStatusChange?.(true)
        }
      } catch (e) {
        if (mountedRef.current && oidRef.current === runOid && inline) onStatusChange?.(true)
        else if (mountedRef.current && oidRef.current === runOid) setErr(mapGmailError(e))
      } finally {
        if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(false)
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) setErr(mapGmailError(e))
    } finally {
      if (mountedRef.current && oidRef.current === runOid) {
        if (!awaitingOAuthRef.current) setBusy(false)
      }
    }
  }, [onStatusChange, oid, resolveMailboxForResync])

  const statusText  = resolving ? 'Loading…' : isActive ? 'Active' : 'Not connected'
  const statusColor = isActive ? GREEN : '#94A3B8'
  /** API sends `total_files`; UI labels it "threads" for Gmail. */
  const gmailThreadCount = Number(
    metrics?.total_files ?? metrics?.total_threads ?? metrics?.thread_count ?? 0,
  )

  return (
    <>
      <style>{`
        @keyframes gmailOppSpin       { to { transform: rotate(360deg) } }
        @keyframes gmailOppPulseRing  { 0% { transform: scale(1); opacity: .6; } 70% { transform: scale(2.2); opacity: 0; } 100% { transform: scale(1); opacity: 0; } }
        @keyframes gmailOppFadeIn     { from { opacity: 0 } to { opacity: 1 } }
        @keyframes gmailOppSlideUp    { from { opacity: 0; transform: translateY(10px) } to { opacity: 1; transform: none } }
        @keyframes gmailOppPulse      { 0%, 100% { opacity: .45 } 50% { opacity: 1 } }
      `}</style>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 22px', borderBottom: isActive ? '1px solid var(--border)' : 'none',
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: 'rgba(234,67,53,.06)', border: '1.5px solid rgba(234,67,53,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <GmailIcon size={22} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>Gmail</span>
            {isActive && (
              <span style={{
                fontSize: 9, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase',
                padding: '2px 8px', borderRadius: 4,
                background: 'rgba(16,185,129,.1)', border: '1px solid rgba(16,185,129,.28)', color: '#059669',
              }}>Active</span>
            )}
            <Dot active={isActive} />
            <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>{statusText}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Email Threads</div>

          {hook.identity?.userEmail && (
            <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2 }}>
              <span style={{ fontWeight: 600 }}>Mailbox (this opportunity): </span>
              <span style={{ color: 'var(--text1)', fontWeight: 700 }}>{hook.identity.userEmail}</span>
            </div>
          )}
          {!hook.identity?.userEmail && (
            <div style={{ fontSize: 10.5, color: '#94A3B8', marginTop: 2 }}>
              Not connected — click Connect and enter a Gmail address for this project.
            </div>
          )}
        </div>

        {!isActive && !resolving && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { if (!awaitingOAuth) { setErr(null); setConnectModal(true) } }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${GMAIL_RED}`,
              background: GMAIL_RED, color: '#fff',
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {awaitingOAuth ? 'Waiting for authorisation…' : busy ? 'Syncing project data…' : 'Connect Gmail'}
          </button>
        )}
        {isActive && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); void handleResync() }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${GMAIL_RED}`,
              background: 'rgba(234,67,53,.1)', color: GMAIL_RED,
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? 'Syncing project data…' : 'Resync'}
          </button>
        )}
      </div>

      {isActive && metricsLoading && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(234,67,53,.12)',
            background: 'rgba(234,67,53,.02)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <SpinIcon size={12} style={{ color: GMAIL_RED }} />
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: GMAIL_RED }}>
                Loading metrics…
              </span>
            </div>
            {[90, 60].map((w, i) => (
              <div key={i} style={{
                height: 10, borderRadius: 5, marginBottom: 6,
                width: `${w}%`, background: 'rgba(234,67,53,.1)',
                animation: 'gmailOppPulse 1.4s ease-in-out infinite',
                animationDelay: `${i * 0.15}s`,
              }} />
            ))}
          </div>
        </div>
      )}

      {isActive && !metricsLoading && metrics && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(234,67,53,.15)',
            background: 'rgba(234,67,53,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '8px 14px', borderBottom: '1px solid rgba(234,67,53,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={GMAIL_RED} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: GMAIL_RED }}>
                Sync metadata
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 14px 16px' }}>
              <div style={{
                flex: '1 1 120px',
                padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(234,67,53,.1)' : 'none',
              }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>Total threads</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 22, fontWeight: 800, color: NAVY, lineHeight: 1 }}>{gmailThreadCount}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--text2)' }}>
                    {gmailThreadCount === 1 ? 'thread' : 'threads'}
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

      {isActive && !metricsLoading && !metrics && !resolving && (
        <div style={{ padding: '10px 22px 14px 80px' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text2)', fontWeight: 600 }}>
            Connected — metrics not available yet.
          </span>
        </div>
      )}

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

      {connectModal && (
        <GmailConnectModal
          initialEmail={hook.identity?.userEmail ?? ''}
          onSubmit={runConnectPipeline}
          onCancel={() => setConnectModal(false)}
        />
      )}
    </>
  )
}
