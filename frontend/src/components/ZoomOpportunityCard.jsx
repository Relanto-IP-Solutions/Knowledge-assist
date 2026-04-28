/**
 * Zoom — Sources page (guide): discover → connect (sync ingest) → metrics.
 * GET metrics on load when already ACTIVE. Connect/Resync run APIs immediately (spinner until done).
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { toApiOpportunityId } from '../config/opportunityApi'
import {
  connectZoom,
  discoverZoom,
  fetchZoomMetrics,
  getCachedZoomConnectInfo,
  getCachedZoomMetrics,
  ZOOM_DISCOVER_DEFAULT_DAYS,
} from '../services/integrationsAuthApi'
import { ZoomIcon } from './SourceIcons'

const ZOOM_BLUE = '#2D8CFF'
const NAVY = '#1B264F'
const GREEN = '#10B981'
const BLUE = '#3B82F6'
const SS_ZOOM_ACTIVE = (oid) => `pzf_zoom_active_${oid}`
const SS_ZOOM_METRICS = (oid) => `pzf_zoom_metrics_view_${oid}`

function ssGet(key) { try { return sessionStorage.getItem(key) } catch { return null } }
function ssSet(key, val) { try { sessionStorage.setItem(key, val) } catch { /**/ } }
function ssGetJson(key) {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function timeAgo(iso) {
  if (!iso) return null
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function SpinIcon({ size = 13 }) {
  return (
    <svg style={{ animation: 'spin .9s linear infinite', flexShrink: 0 }}
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
  )
}

function Dot({ state }) {
  const map = { idle: '#CBD5E1', active: GREEN, syncing: BLUE }
  const c = map[state] || map.idle
  return (
    <>
      <style>{`
        @keyframes pulseRing {
          0%   { transform: scale(1);   opacity: .6; }
          70%  { transform: scale(2.2); opacity: 0;  }
          100% { transform: scale(1);   opacity: 0;  }
        }
      `}</style>
      <span style={{ position: 'relative', width: 8, height: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {(state === 'active' || state === 'syncing') && (
          <span style={{
            position: 'absolute', width: 8, height: 8, borderRadius: '50%',
            background: c, animation: 'pulseRing 1.6s ease-out infinite',
          }} />
        )}
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, position: 'relative' }} />
      </span>
    </>
  )
}

export default function ZoomOpportunityCard({ opportunityId, onStatusChange }) {
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])
  const cachedInfo = getCachedZoomConnectInfo(oid)
  const sessionMetrics = ssGetJson(SS_ZOOM_METRICS(oid))

  const [active, setActive] = useState(() => (
    cachedInfo?.status === 'ACTIVE'
    || ssGet(SS_ZOOM_ACTIVE(oid)) === '1'
    || Boolean(sessionMetrics)
  ))
  const [metrics, setMetrics] = useState(() => getCachedZoomMetrics(oid) ?? sessionMetrics)
  const [metricsLoading, setMetricsLoading] = useState(() => {
    return (cachedInfo?.status === 'ACTIVE' || ssGet(SS_ZOOM_ACTIVE(oid)) === '1') && !(getCachedZoomMetrics(oid) ?? sessionMetrics)
  })
  const [busy, setBusy] = useState(false)
  /** 'discover' | 'connect' | 'metrics' — which API phase is running */
  const [ingestStep, setIngestStep] = useState(null)
  const [discoveryResult, setDiscoveryResult] = useState(null)
  const [err, setErr] = useState(null)

  const mountedRef = useRef(true)
  /** Viewed opportunity; async connect/resync for `runOid` may finish after navigation — APIs still persist per-oid cache. */
  const oidRef = useRef(oid)
  oidRef.current = oid

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    const info = getCachedZoomConnectInfo(oid)
    const cachedM = getCachedZoomMetrics(oid) ?? ssGetJson(SS_ZOOM_METRICS(oid))
    const persistedActive = ssGet(SS_ZOOM_ACTIVE(oid)) === '1'
    setActive(info?.status === 'ACTIVE' || persistedActive || Boolean(cachedM))
    setMetrics(cachedM ?? null)
    setMetricsLoading((info?.status === 'ACTIVE' || persistedActive) && !cachedM)
    setDiscoveryResult(null)
    setErr(null)
    setBusy(false)
    setIngestStep(null)
  }, [oid])

  useEffect(() => {
    ssSet(SS_ZOOM_ACTIVE(oid), active ? '1' : '0')
    if (metrics) ssSet(SS_ZOOM_METRICS(oid), JSON.stringify(metrics))
  }, [oid, active, metrics])

  useEffect(() => {
    onStatusChange?.(active)
  }, [active, onStatusChange])

  /**
   * Session cache: show cached metrics immediately when revisiting this opportunity —
   * only fetch when ACTIVE but no metrics stored yet (first load after connect).
   */
  useEffect(() => {
    const cachedInfo = getCachedZoomConnectInfo(oid)
    if (cachedInfo?.status !== 'ACTIVE') return
    const cachedM = getCachedZoomMetrics(oid)
    if (cachedM) {
      setMetrics(cachedM)
      setMetricsLoading(false)
      return
    }
    let alive = true
    setMetricsLoading(true)
    fetchZoomMetrics(oid)
      .then(m => { if (alive) setMetrics(m) })
      .catch(() => { if (alive) setMetrics(getCachedZoomMetrics(oid) ?? null) })
      .finally(() => { if (alive) setMetricsLoading(false) })
    return () => { alive = false }
  }, [oid])

  const refreshStateFromCache = useCallback(() => {
    setActive(getCachedZoomConnectInfo(oid)?.status === 'ACTIVE')
    setMetrics(getCachedZoomMetrics(oid))
  }, [oid])

  const handleConnect = useCallback(async () => {
    const runOid = oid
    setBusy(true)
    setErr(null)
    try {
      setIngestStep('discover')
      const discovered = await discoverZoom(runOid, ZOOM_DISCOVER_DEFAULT_DAYS)
      if (mountedRef.current && oidRef.current === runOid) setDiscoveryResult(discovered)

      setIngestStep('connect')
      const connected = await connectZoom(runOid)
      if (!mountedRef.current || oidRef.current !== runOid) return

      refreshStateFromCache()
      if (connected?.status === 'ACTIVE' || connected?.total_files != null) {
        setActive(true)
        onStatusChange?.(true)
      }

      // Fetch metrics in background so Connect feels snappier.
      setMetricsLoading(true)
      setBusy(false)
      setIngestStep(null)
      try {
        const m = await fetchZoomMetrics(runOid)
        if (mountedRef.current && oidRef.current === runOid) setMetrics(m)
      } catch {
        if (mountedRef.current && oidRef.current === runOid && connected) setMetrics(connected)
      } finally {
        if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(false)
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) {
        setErr(e?.response?.data?.detail ?? e?.message ?? 'Zoom setup failed. Try again.')
      }
    } finally {
      if (mountedRef.current && oidRef.current === runOid) {
        setBusy(false)
        setIngestStep(null)
      }
    }
  }, [oid, onStatusChange, refreshStateFromCache])

  const handleResync = useCallback(async () => {
    const runOid = oid
    setBusy(true)
    setErr(null)
    try {
      setIngestStep('connect')
      const connected = await connectZoom(runOid)
      if (!mountedRef.current || oidRef.current !== runOid) return
      refreshStateFromCache()
      setActive(true)
      onStatusChange?.(true)

      // Refresh metrics in background; unblock card interactions immediately.
      setMetricsLoading(true)
      setBusy(false)
      setIngestStep(null)
      try {
        const m = await fetchZoomMetrics(runOid)
        if (mountedRef.current && oidRef.current === runOid) setMetrics(m)
      } catch {
        if (mountedRef.current && oidRef.current === runOid && connected) setMetrics(connected)
      } finally {
        if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(false)
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid) {
        setErr(e?.response?.data?.detail ?? e?.message ?? 'Resync failed. Try again.')
      }
    } finally {
      if (mountedRef.current && oidRef.current === runOid) {
        setBusy(false)
        setIngestStep(null)
      }
    }
  }, [oid, onStatusChange, refreshStateFromCache])

  const dotState = busy ? 'syncing' : active ? 'active' : 'idle'
  let statusText = 'Not connected'
  if (active) statusText = 'Active'
  else if (busy && ingestStep === 'discover') statusText = 'Scanning organization…'
  else if (busy && ingestStep === 'connect') statusText = 'Syncing recordings (10–20s typical)…'
  else if (busy && ingestStep === 'metrics') statusText = 'Loading metrics…'
  else if (busy) statusText = 'Working…'

  const statusColor = active ? GREEN : busy ? BLUE : '#94A3B8'
  const recordingsScanned = discoveryResult?.recordings_scanned
  const recordingsWithOid = discoveryResult?.recordings_with_oid

  let busyLabel = 'Working…'
  if (ingestStep === 'discover') busyLabel = 'Discovering…'
  else if (ingestStep === 'connect') busyLabel = 'Syncing…'
  else if (ingestStep === 'metrics') busyLabel = 'Metrics…'

  const totalFilesCount = Number(metrics?.total_files ?? 0)

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes pulse { 0%, 100% { opacity: .45 } 50% { opacity: 1 } }
      `}</style>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 22px', borderBottom: active ? '1px solid var(--border)' : 'none',
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: 'rgba(45,140,255,.06)', border: '1.5px solid rgba(45,140,255,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <ZoomIcon size={22} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>Zoom</span>
            <Dot state={dotState} />
            <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>{statusText}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Meetings & Recordings</div>
          <div style={{ fontSize: 10.5, color: '#64748B', marginTop: 2 }}>
            Org-wide discovery, then synchronous ingest to storage, then metrics (project <strong>{oid}</strong>, last {ZOOM_DISCOVER_DEFAULT_DAYS} days).
          </div>
          {recordingsScanned != null && recordingsWithOid != null && (
            <div style={{
              marginTop: 8, fontSize: 10.5, fontWeight: 600, color: '#0F766E',
              padding: '6px 10px', borderRadius: 8,
              background: 'rgba(16,185,129,.08)', border: '1px solid rgba(16,185,129,.22)',
            }}>
              Last discover: {recordingsScanned} recordings scanned · {recordingsWithOid} match this project
              {discoveryResult?.opportunities_created > 0 && ` · ${discoveryResult.opportunities_created} new opps`}
            </div>
          )}
        </div>

        {!active && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); void handleConnect() }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${ZOOM_BLUE}`,
              background: ZOOM_BLUE, color: '#fff',
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? busyLabel : 'Connect'}
          </button>
        )}
        {active && (
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); void handleResync() }}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: busy ? 'not-allowed' : 'pointer',
              border: `1.5px solid ${ZOOM_BLUE}`,
              background: 'rgba(45,140,255,.1)', color: ZOOM_BLUE,
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? busyLabel : 'Resync'}
          </button>
        )}
      </div>

      {active && metricsLoading && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(45,140,255,.12)',
            background: 'rgba(45,140,255,.02)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <SpinIcon size={12} style={{ color: ZOOM_BLUE }} />
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: ZOOM_BLUE }}>
                Loading metrics…
              </span>
            </div>
            {[90, 60].map((w, i) => (
              <div key={i} style={{
                height: 10, borderRadius: 5, marginBottom: 6,
                width: `${w}%`, background: 'rgba(45,140,255,.1)',
                animation: 'pulse 1.4s ease-in-out infinite',
                animationDelay: `${i * 0.15}s`,
              }} />
            ))}
          </div>
        </div>
      )}

      {active && !metricsLoading && metrics && (
        <div style={{ padding: '12px 22px 18px 80px' }}>
          <div style={{
            borderRadius: 12, border: '1px solid rgba(45,140,255,.15)',
            background: 'rgba(45,140,255,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '9px 16px 8px', borderBottom: '1px solid rgba(45,140,255,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={ZOOM_BLUE} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: ZOOM_BLUE }}>
                Sync metadata
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 16px 16px' }}>
              <div style={{
                flex: '1 1 120px',
                padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(45,140,255,.1)' : 'none',
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

      {active && !metricsLoading && !metrics && (
        <div style={{ padding: '10px 22px 14px 80px' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text2)', fontWeight: 600 }}>
            Connected — metrics not available yet.
          </span>
        </div>
      )}

      {err && (
        <div style={{ padding: '0 22px 14px 80px' }}>
          <span style={{ fontSize: 12, color: '#DC2626' }}>{err}</span>
        </div>
      )}
    </>
  )
}
