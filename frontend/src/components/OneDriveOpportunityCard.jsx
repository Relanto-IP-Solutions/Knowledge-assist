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

const SS_EMAIL          = (oid) => `pzf_onedrive_email_${oid}`
const SS_PENDING_OID    = 'pzf_onedrive_pending_oid'
const SS_PENDING_EMAIL  = 'pzf_onedrive_pending_email'
const SS_AUTH_DONE      = (oid) => `pzf_onedrive_auth_done_${oid}`
// Persists the "no OneDrive folder for this OID" signal across reloads.
// Backend returns a 404 on connect when the folder is missing; once the user
// navigates away and back the 404 isn't re-issued, so without this flag the
// hint would silently disappear.
const SS_FOLDER_MISSING = (oid) => `pzf_onedrive_folder_missing_${oid}`

function isOneDriveMissingFolderError(detail, status) {
  if (status === 404) return true
  const msg = String(detail ?? '').trim().toLowerCase()
  if (!msg) return false
  return (
    (msg.includes('onedrive') && msg.includes('folder') && msg.includes('not found')) ||
    msg.includes('no project folder found') ||
    msg.includes("couldn't find a folder") ||
    msg.includes('please create it manually')
  )
}

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

// Phase stepper rendered while a connect/sync operation is in flight. Maps
// the current `phase` to one of three steps: Connect → Sync → Ready.
function PhaseStepper({ phase }) {
  const steps = [
    { key: 'connect', label: 'Connect', activePhases: ['authorizing', 'connecting'] },
    { key: 'sync',    label: 'Sync',    activePhases: ['indexing'] },
    { key: 'ready',   label: 'Ready',   activePhases: [] },
  ]
  const order = { authorizing: 0, connecting: 0, indexing: 1, idle: 2 }
  const currentIdx = order[phase] ?? 0

  const subtitle = (() => {
    if (phase === 'authorizing') return 'Authorizing with Microsoft…'
    if (phase === 'connecting')  return 'Locating your OneDrive folder…'
    if (phase === 'indexing')    return 'Indexing your files in the background…'
    return ''
  })()

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      padding: '10px 12px', borderRadius: 10,
      border: '1px solid rgba(0,120,212,.18)',
      background: 'rgba(0,120,212,.04)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {steps.map((step, i) => {
          const isActiveStep   = i === currentIdx
          const isCompleteStep = i < currentIdx
          const nodeColor = isCompleteStep ? OD_BLUE : isActiveStep ? OD_BLUE : '#CBD5E1'
          const nodeBg    = isCompleteStep || isActiveStep ? OD_BLUE : 'transparent'
          const textColor = isActiveStep ? OD_BLUE : isCompleteStep ? NAVY : '#94A3B8'
          return (
            <div key={step.key} style={{ display: 'flex', alignItems: 'center', flex: i === steps.length - 1 ? '0 0 auto' : 1, gap: 6 }}>
              <div style={{
                width: 18, height: 18, borderRadius: '50%',
                border: `1.5px solid ${nodeColor}`, background: nodeBg,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', flexShrink: 0,
              }}>
                {isCompleteStep ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                ) : isActiveStep ? (
                  <SpinIcon size={9} />
                ) : null}
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, color: textColor, letterSpacing: '.02em' }}>{step.label}</span>
              {i < steps.length - 1 && (
                <div style={{
                  flex: 1, height: 2, marginLeft: 4, marginRight: 2,
                  background: i < currentIdx ? OD_BLUE : '#E2E8F0',
                  borderRadius: 2,
                }} />
              )}
            </div>
          )
        })}
      </div>
      {subtitle && (
        <span style={{ fontSize: 11, color: 'var(--text2)', fontWeight: 500 }}>{subtitle}</span>
      )}
    </div>
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
  // Phase machine for the Connect → Sync → Ready progression.
  // 'idle'        -> nothing in flight; metrics block is allowed to render
  // 'authorizing' -> getMicrosoftOAuthUrl / waiting on Microsoft consent
  // 'connecting'  -> POST /onedrive/connect (folder lookup, source upsert)
  // 'indexing'    -> connect returned ACTIVE; backend BackgroundTask is
  //                  ingesting files. We poll metrics silently and watch
  //                  for source.last_synced_at to flip from null.
  const [phase, setPhase]                   = useState('idle')
  // Distinguishes a Resync (source was already active) from an initial
  // Connect. The stepper is reserved for first-time connects — during
  // a Resync the button's disabled+spinner state is sufficient feedback.
  const [isResync, setIsResync]             = useState(false)
  const [folderMissing, setFolderMissing]   = useState(() => ssGet(SS_FOLDER_MISSING(oid)) === '1')
  // UI-level connection state: do not rely solely on metrics.status because
  // connect can succeed (or return folder-missing) before metrics carry ACTIVE.
  const [isConnected, setIsConnected]       = useState(() => {
    const cached = getCachedOneDriveMetrics(oid)
    return String(cached?.status ?? '').toUpperCase() === 'ACTIVE' || ssGet(SS_FOLDER_MISSING(oid)) === '1'
  })
  const [copiedOid, setCopiedOid]           = useState(false)

  const mountedRef = useRef(true)
  const oidRef     = useRef(oid)
  oidRef.current   = oid

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false } }, [])

  const isActive = isConnected || String(metrics?.status ?? '').toUpperCase() === 'ACTIVE'

  useEffect(() => { onStatusChange?.(isActive) }, [isActive, onStatusChange])

  // Load metrics on mount
  useEffect(() => {
    const cached = getCachedOneDriveMetrics(oid)
    setIsConnected(String(cached?.status ?? '').toUpperCase() === 'ACTIVE' || ssGet(SS_FOLDER_MISSING(oid)) === '1')
    setFolderMissing(ssGet(SS_FOLDER_MISSING(oid)) === '1')
  }, [oid])

  useEffect(() => {
    let alive = true
    const hasCache = getCachedOneDriveMetrics(oid) !== null
    if (!hasCache) setMetricsLoading(true)
    fetchOneDriveMetrics(oid)
      .then(m => {
        if (alive) {
          setMetrics(m)
          if (String(m?.status ?? '').toUpperCase() === 'ACTIVE') setIsConnected(true)
          setMetricsLoading(false)
        }
      })
      .catch(() => { if (alive) setMetricsLoading(false) })
    return () => { alive = false }
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
    ssSet(SS_AUTH_DONE(oid), '1')
    // Keep post-redirect flow in-place. Next Connect/Resync proceeds directly
    // to sync without forcing OAuth again.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const doRedirect = useCallback((runOid, email, authUrl) => {
    ssSet(SS_PENDING_OID, runOid)
    ssSet(SS_PENDING_EMAIL, email)
    window.location.href = String(authUrl).trim()
  }, [])

  // Core: POST connect → wait for backend ingestion → fetch real metrics.
  //
  // The backend BackgroundTask runs after /connect returns, so we poll
  // /metrics silently (without writing to UI state) and watch for
  // last_synced_at to become non-null. Only when sync is verifiably
  // complete do we fetch the metrics one final time and reveal them.
  const runConnectAndMetrics = useCallback(async (runOid, email, options = {}) => {
    const allowOAuthRedirect = options.allowOAuthRedirect !== false
    if (!mountedRef.current) return
    setBusy(true)
    setNotice(null)
    setPhase('connecting')

    try {
      await connectOneDrive(runOid, email)
      setIsConnected(true)
      // Reached only on 2xx — backend confirmed the folder exists and queued
      // the background sync. Clear any persisted "missing folder" hint so a
      // user who just created the folder and re-synced sees the success path.
      setFolderMissing(false)
      ssSet(SS_FOLDER_MISSING(runOid), '0')
    } catch (e) {
      if (!mountedRef.current || oidRef.current !== runOid) return
      const status = e?.response?.status
      const detail = e?.response?.data?.detail ?? ''

      if (status === 401 || status === 400) {
        if (allowOAuthRedirect) {
          // First-time flow: no valid token/connection yet, route to OAuth.
          setPhase('authorizing')
          try {
            const auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, runOid)
            if (auth?.auth_url) { doRedirect(runOid, email, auth.auth_url); return }
          } catch { /**/ }
        }
        if (mountedRef.current) {
          setIsConnected(false)
          setNotice({
            type: 'error',
            msg: allowOAuthRedirect ? 'Please login to OneDrive first.' : 'Unable to sync OneDrive right now. Try Resync again.',
          })
          setPhase('idle')
          setIsResync(false)
          setBusy(false)
        }
        return
      }

      if (status === 403) {
        setIsConnected(false)
        setNotice({ type: 'error', msg: 'Only @relanto.ai accounts are permitted.' })
        setPhase('idle')
        setIsResync(false)
        setBusy(false)
        return
      }

      // Missing-folder response — typically 404, but we also match the
      // backend message text so any status/detail drift still shows the
      // actionable banner instead of raw red inline errors.
      if (isOneDriveMissingFolderError(detail, status)) {
        setIsConnected(true)
        setFolderMissing(true)
        ssSet(SS_FOLDER_MISSING(runOid), '1')
        setNotice(null)
      } else {
        const fallback = detail || 'OneDrive sync failed. Try again.'
        setNotice({ type: 'error', msg: fallback })
      }
      setPhase('idle')
      setIsResync(false)
      setBusy(false)
      return
    }

    if (!mountedRef.current || oidRef.current !== runOid) return

    setPhase('indexing')

    // Silently poll until source.last_synced_at flips from null. We do not
    // call setMetrics here so the UI does not surface a stale or 0-file
    // snapshot mid-sync. 60s budget (20 × 3s); on timeout we still fall
    // through to one final fetch so the metrics block can hydrate as soon
    // as data is available.
    const POLL_INTERVAL = 3000
    const MAX_ATTEMPTS  = 20
    for (let i = 0; i < MAX_ATTEMPTS; i++) {
      if (!mountedRef.current || oidRef.current !== runOid) return
      try {
        const m = await fetchOneDriveMetrics(runOid)
        if (Boolean(m?.last_synced_at)) break
      } catch { /**/ }
      if (i < MAX_ATTEMPTS - 1) await new Promise(r => setTimeout(r, POLL_INTERVAL))
    }

    if (!mountedRef.current || oidRef.current !== runOid) return

    // One authoritative metrics fetch, now that sync is (likely) done. This
    // is what the user sees in the metrics block.
    let finalMetrics = null
    try { finalMetrics = await fetchOneDriveMetrics(runOid) } catch { /**/ }

    if (!mountedRef.current || oidRef.current !== runOid) return

    if (finalMetrics) setMetrics(finalMetrics)
    if (String(finalMetrics?.status ?? '').toUpperCase() === 'ACTIVE') setIsConnected(true)

    // Once the source is connected, the green "Active" pill in the header
    // (and the metrics block, if last_synced_at is set) is the entire
    // confirmation. No extra notices — they were redundant with the
    // header status.
    setNotice(null)
    setPhase('idle')
    setIsResync(false)
    setBusy(false)
  }, [doRedirect])

  // ── Connect flow ─────────────────────────────────────────────────
  const handleConnectWithEmail = useCallback(async (email) => {
    setShowModal(false)
    setUserEmail(email)
    ssSet(SS_EMAIL(oid), email)
    setBusy(true)
    setNotice(null)
    // If the user just returned from Microsoft OAuth (or is already connected),
    // skip the extra authorize hop and go straight to connect+sync.
    setPhase('connecting')

    try {
      const info = await getOneDriveAuthorizeInfo(oid, email)
      if (info?.has_onedrive_connection === true) {
        ssSet(SS_AUTH_DONE(oid), '1')
        await runConnectAndMetrics(oid, email, { allowOAuthRedirect: false })
        return
      }
    } catch {
      // Non-fatal: fall through to OAuth URL check below.
    }

    const hasAuthedBefore = ssGet(SS_AUTH_DONE(oid)) === '1'
    let auth = null
    try {
      setPhase('authorizing')
      auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, oid)
    } catch (e) {
      if (!mountedRef.current) return
      const status = e?.response?.status
      if (status === 403) {
        setNotice({ type: 'error', msg: 'Only @relanto.ai accounts are permitted.' })
        setPhase('idle')
        setBusy(false)
        return
      }
      // Error body might still carry an auth_url
      const authUrl = e?.response?.data?.auth_url
      if (authUrl) { doRedirect(oid, email, authUrl); return }
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setPhase('idle')
      setBusy(false)
      return
    }

    if (!mountedRef.current) return

    if (auth?.already_connected === true) {
      ssSet(SS_AUTH_DONE(oid), '1')
      // runConnectAndMetrics will move phase from 'authorizing' -> 'connecting'.
      await runConnectAndMetrics(oid, email, { allowOAuthRedirect: false })
    } else if (auth?.auth_url) {
      if (hasAuthedBefore) {
        // User already completed first-time login for this OID — do not
        // auto-redirect to auth again.
        await runConnectAndMetrics(oid, email, { allowOAuthRedirect: false })
      } else {
        doRedirect(oid, email, auth.auth_url)
      }
    } else {
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setPhase('idle')
      setBusy(false)
    }
  }, [oid, doRedirect, runConnectAndMetrics])

  const handleConnect = useCallback(() => {
    setNotice(null)
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (!email || !RELANTO_RE.test(email)) { setShowModal(true); return }
    void handleConnectWithEmail(email)
  }, [oid, userEmail, handleConnectWithEmail])

  const handleCopyOid = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(oid)
      setCopiedOid(true)
      setTimeout(() => setCopiedOid(false), 1800)
    } catch { /* clipboard unavailable */ }
  }, [oid])

  // ── Resync flow ──────────────────────────────────────────────────
  const handleResync = useCallback(async () => {
    const email = userEmail || ssGet(SS_EMAIL(oid)) || ''
    if (!email) { setShowModal(true); return }

    setBusy(true)
    setNotice(null)
    setCopiedOid(false)
    setIsResync(true) // suppresses the stepper for already-active sources
    setPhase('authorizing') // brief: confirming the connection still holds

    // Step 1: check authorize-info to confirm connection exists
    let authorizeInfo = null
    try {
      authorizeInfo = await getOneDriveAuthorizeInfo(oid, email)
    } catch { /* unknown — proceed to connect and let it decide */ }

    if (!mountedRef.current || oidRef.current !== oid) return

    const hasAuthedBefore = ssGet(SS_AUTH_DONE(oid)) === '1'
    if (authorizeInfo?.has_onedrive_connection === false && !hasAuthedBefore) {
      setIsConnected(false)
      // No connection — route to OAuth
      try {
        const auth = await getMicrosoftOAuthUrl(getOneDriveOAuthRedirectUri(), email, oid)
        if (auth?.auth_url) { doRedirect(oid, email, auth.auth_url); return }
      } catch { /**/ }
      setNotice({ type: 'error', msg: 'Please login to OneDrive first.' })
      setPhase('idle')
      setIsResync(false)
      setBusy(false)
      return
    }

    // Connection exists (or unknown) — always allow one OAuth recovery hop on
    // auth failures (400/401). This handles token-expired/deleted scenarios
    // for users who were connected previously.
    await runConnectAndMetrics(oid, email, { allowOAuthRedirect: true })
  }, [oid, userEmail, doRedirect, runConnectAndMetrics])

  const totalFilesCount = Number(metrics?.total_files ?? 0)
  const noticeColor = notice?.type === 'success' ? '#047857' : notice?.type === 'info' ? OD_BLUE : '#DC2626'
  const inFlight = phase !== 'idle'
  // Stepper is reserved for first-time connects. During a Resync the
  // existing metrics block stays visible and the disabled/spinning button
  // is sufficient feedback — adding the stepper would just flash a redundant
  // "Connect → Sync" graphic over an already-active source.
  const showStepper = inFlight && !isResync
  // Metrics block only renders for a fully-synced source. last_synced_at is
  // the only signal that the backend BackgroundTask actually completed, so
  // we never reveal the metrics block before that — preventing the
  // misleading "0 files" snapshot the user reported. During a resync we
  // keep showing the previous metrics until the fresh fetch lands. We also
  // suppress it whenever we know the project folder is missing, since
  // "0 files" without context is just confusing — the missing-folder
  // banner below tells the user exactly what to do.
  const showMetricsBlock = (!inFlight || isResync) && isActive && Boolean(metrics?.last_synced_at) && !folderMissing
  const showFolderMissingBanner = folderMissing && !inFlight
  const hasContentBelow = showStepper || Boolean(notice) || showMetricsBlock || showFolderMissingBanner

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
        padding: '18px 22px', borderBottom: hasContentBelow ? '1px solid var(--border)' : 'none',
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
          {/* Only surface the account once the source is genuinely active.
              If a connect attempt fails (e.g. 404 folder-not-found), we
              suppress the email so the UI doesn't claim a connection that
              isn't really established. */}
          {isActive && userEmail && (
            <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2 }}>
              <span style={{ fontWeight: 600 }}>Account: </span>
              <span style={{ color: NAVY, fontWeight: 700 }}>{userEmail}</span>
            </div>
          )}
        </div>

        {/* Connect — not active. Label stays constant; the stepper below
            is the single source of phase detail (Connect → Sync → Ready). */}
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
            Connect
          </button>
        )}

        {/* Resync — active */}
        {!metricsLoading && isActive && (
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
            Resync
          </button>
        )}
      </div>

      {/* Phase stepper — shown only on first-time connects, hidden on resyncs */}
      {showStepper && (
        <div style={{ padding: '12px 22px 14px 80px' }}>
          <PhaseStepper phase={phase} />
        </div>
      )}

      {/* Notice — only when idle, so the stepper is the sole indicator during work */}
      {notice && !inFlight && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: noticeColor }}>{notice.msg}</span>
        </div>
      )}

      {/* Missing-folder hint — backend returned 404 from /onedrive/connect
          because no folder containing this OID exists in the user's
          OneDrive. Tells them what to name the folder and offers a
          one-click copy of the project id. */}
      {showFolderMissingBanner && (
        <div style={{ padding: '10px 22px 14px 80px' }}>
          <div style={{
            display: 'flex', gap: 12, padding: '12px 14px', borderRadius: 10,
            background: 'rgba(234,179,8,.08)', border: '1px solid rgba(234,179,8,.35)',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#B45309" strokeWidth="2" strokeLinecap="round" style={{ flexShrink: 0, marginTop: 2 }}>
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: '#92400E', marginBottom: 4 }}>
                No project folder found in OneDrive
              </div>
              <div style={{ fontSize: 11.5, color: '#92400E', lineHeight: 1.55, marginBottom: 8 }}>
                Create a folder in your OneDrive with this project id in the name, add your files there, then click <strong>Resync</strong>. Recommended names: <code style={{ background: 'rgba(146,64,14,.1)', padding: '1px 5px', borderRadius: 4, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{oid}</code>, <code style={{ background: 'rgba(146,64,14,.1)', padding: '1px 5px', borderRadius: 4, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{`OID ${oid.replace(/^oid/i, '')}`}</code>, or <code style={{ background: 'rgba(146,64,14,.1)', padding: '1px 5px', borderRadius: 4, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{`Project ${oid}`}</code>.
              </div>
              <button type="button" onClick={handleCopyOid}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '5px 11px', borderRadius: 6,
                  border: '1px solid rgba(146,64,14,.35)', background: '#fff',
                  color: '#92400E', fontSize: 11, fontWeight: 700,
                  cursor: 'pointer', fontFamily: 'var(--font)',
                }}
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                {copiedOid ? 'Copied!' : `Copy ${oid}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Metrics — gated on phase === 'idle' AND a real last_synced_at */}
      {showMetricsBlock && (
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
