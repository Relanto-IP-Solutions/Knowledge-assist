/**
 * Slack — Sources page (guide): discover → connect (sync ingest) → metrics.
 * GET metrics on load when already ACTIVE. Connect/Resync run APIs immediately (spinner until done).
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { toApiOpportunityId } from '../config/opportunityApi'
import {
  connectSlack,
  fetchSlackConnectInfo,
  fetchSlackMetrics,
  getCachedSlackConnectInfo,
  getCachedSlackMetrics,
  orchestrateSlack,
} from '../services/integrationsAuthApi'
import { SlackIcon } from './SourceIcons'

const SLACK_COLOR = '#4A154B'
const NAVY = '#1B264F'
const GREEN = '#10B981'
const BLUE = '#3B82F6'

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

export default function SlackOpportunityCard({ opportunityId, onStatusChange }) {
  const oid = useMemo(() => toApiOpportunityId(opportunityId), [opportunityId])

  const [active, setActive] = useState(() => getCachedSlackConnectInfo(oid)?.status === 'ACTIVE')
  const [metrics, setMetrics] = useState(() => getCachedSlackMetrics(oid))
  const [metricsLoading, setMetricsLoading] = useState(() => {
    const info = getCachedSlackConnectInfo(oid)
    return info?.status === 'ACTIVE' && !getCachedSlackMetrics(oid)
  })
  const [busy, setBusy] = useState(false)
  /** 'discover' | 'connect' | 'metrics' — which API phase is running */
  const [ingestStep, setIngestStep] = useState(null)
  const [err, setErr] = useState(null)

  const [showCreateChannel, setShowCreateChannel] = useState(false)
  const [channelName, setChannelName] = useState('')
  const [teamEmailsInput, setTeamEmailsInput] = useState('')
  const [orchestrateBusy, setOrchestrateBusy] = useState(false)
  const [orchestrateResult, setOrchestrateResult] = useState(null)
  const [orchestrateErr, setOrchestrateErr] = useState(null)

  const mountedRef = useRef(true)
  /** Tracks the opportunity currently shown; connect/resync started for `runOid` may finish after navigation — still persist via API cache. */
  const oidRef = useRef(oid)
  oidRef.current = oid

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    const info = getCachedSlackConnectInfo(oid)
    const cachedM = getCachedSlackMetrics(oid)
    setActive(info?.status === 'ACTIVE')
    setMetrics(cachedM ?? null)
    setMetricsLoading(info?.status === 'ACTIVE' && !cachedM)
    setErr(null)
    setBusy(false)
    setIngestStep(null)
  }, [oid])

  useEffect(() => {
    onStatusChange?.(active)
  }, [active, onStatusChange])

  /**
   * Session cache (sessionStorage + in-memory): if this opportunity already has metrics
   * from a prior connect/resync in this tab, show them immediately — do not refetch on revisit.
   */
  useEffect(() => {
    const cachedInfo = getCachedSlackConnectInfo(oid)
    if (cachedInfo?.status !== 'ACTIVE') return
    const cachedM = getCachedSlackMetrics(oid)
    if (cachedM) {
      setMetrics(cachedM)
      setMetricsLoading(false)
      return
    }
    let alive = true
    setMetricsLoading(true)
    fetchSlackMetrics(oid)
      .then(m => { if (alive) setMetrics(m) })
      .catch(() => { if (alive) setMetrics(getCachedSlackMetrics(oid) ?? null) })
      .finally(() => { if (alive) setMetricsLoading(false) })
    return () => { alive = false }
  }, [oid])

  const refreshStateFromCache = useCallback(() => {
    setActive(getCachedSlackConnectInfo(oid)?.status === 'ACTIVE')
    setMetrics(getCachedSlackMetrics(oid))
  }, [oid])

  const handleConnect = useCallback(async () => {
    const runOid = oid
    setBusy(true)
    setErr(null)
    try {
      // Step 1: POST /integrations/slack/connect/{oid}
      setIngestStep('connect')
      await connectSlack(runOid)
      if (!mountedRef.current || oidRef.current !== runOid) return

      // Step 2: GET /integrations/slack/authorize-info/{oid}
      setIngestStep('authorize')
      try {
        const info = await fetchSlackConnectInfo(runOid)
        if (mountedRef.current && oidRef.current === runOid && info?.status === 'ACTIVE') {
          setActive(true)
          onStatusChange?.(true)
        }
      } catch { /**/ }

      if (!mountedRef.current || oidRef.current !== runOid) return
      refreshStateFromCache()
      if (connected?.status === 'ACTIVE') { setActive(true); onStatusChange?.(true) }

      // Step 3: GET /integrations/slack/metrics/{oid}
      setIngestStep('metrics')
      setMetricsLoading(true)
      try {
        const m = await fetchSlackMetrics(runOid)
        if (mountedRef.current && oidRef.current === runOid) setMetrics(m)
      } catch {
        if (mountedRef.current && oidRef.current === runOid && connected) setMetrics(connected)
      } finally {
        if (mountedRef.current && oidRef.current === runOid) setMetricsLoading(false)
      }
    } catch (e) {
      if (mountedRef.current && oidRef.current === runOid)
        setErr(e?.response?.data?.detail ?? e?.message ?? 'Slack setup failed. Try again.')
    } finally {
      if (mountedRef.current && oidRef.current === runOid) {
        setBusy(false)
        setIngestStep(null)
      }
    }
  }, [oid, onStatusChange, refreshStateFromCache])

  const handleCreateChannel = useCallback(async () => {
    const runOid = oid
    const name = channelName.trim() || oid
    const emails = teamEmailsInput
      .split(/[\n,]+/)
      .map(e => e.trim())
      .filter(Boolean)
    setOrchestrateBusy(true)
    setOrchestrateErr(null)
    setOrchestrateResult(null)
    try {
      const result = await orchestrateSlack(runOid, name, emails)
      if (mountedRef.current) setOrchestrateResult(result)
    } catch (e) {
      if (mountedRef.current)
        setOrchestrateErr(e?.response?.data?.detail ?? e?.message ?? 'Channel creation failed. Try again.')
    } finally {
      if (mountedRef.current) setOrchestrateBusy(false)
    }
  }, [oid, channelName, teamEmailsInput])

  const handleResync = useCallback(async () => {
    const runOid = oid
    setBusy(true)
    setErr(null)
    try {
      setIngestStep('connect')
      const connected = await connectSlack(runOid)
      if (!mountedRef.current || oidRef.current !== runOid) return
      refreshStateFromCache()
      setActive(true)
      onStatusChange?.(true)

      setIngestStep('metrics')
      setMetricsLoading(true)
      try {
        const m = await fetchSlackMetrics(runOid)
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
  else if (busy && ingestStep === 'connect') statusText = 'Syncing messages (10–15s typical)…'
  else if (busy && ingestStep === 'authorize') statusText = 'Verifying connection…'
  else if (busy && ingestStep === 'metrics') statusText = 'Loading metrics…'
  else if (busy) statusText = 'Working…'

  const statusColor = active ? GREEN : busy ? BLUE : '#94A3B8'

  let busyLabel = 'Working…'
  if (ingestStep === 'connect') busyLabel = 'Syncing…'
  else if (ingestStep === 'authorize') busyLabel = 'Verifying…'
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
          background: 'rgba(74,21,75,.06)', border: '1.5px solid rgba(74,21,75,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <SlackIcon size={22} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: NAVY }}>Slack</span>
            <Dot state={dotState} />
            <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>{statusText}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Workspace Channels</div>
          <div style={{ fontSize: 10.5, color: '#64748B', marginTop: 2 }}>
            Discover the channel for project <strong>{oid}</strong>, then synchronous ingest to storage. 
          </div>
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
              border: `1.5px solid ${SLACK_COLOR}`,
              background: SLACK_COLOR, color: '#fff',
              fontFamily: 'var(--font)', transition: 'opacity .12s',
              opacity: busy ? 0.55 : 1,
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.opacity = '0.85' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = busy ? '0.55' : '1' }}
          >
            {busy && <SpinIcon size={11} />}
            {busy ? busyLabel : 'Connect Slack'}
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
              border: `1.5px solid ${SLACK_COLOR}`,
              background: 'rgba(74,21,75,.1)', color: SLACK_COLOR,
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
            borderRadius: 12, border: '1px solid rgba(74,21,75,.12)',
            background: 'rgba(74,21,75,.02)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <SpinIcon size={12} style={{ color: SLACK_COLOR }} />
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: SLACK_COLOR }}>
                Loading metrics…
              </span>
            </div>
            {[90, 60].map((w, i) => (
              <div key={i} style={{
                height: 10, borderRadius: 5, marginBottom: 6,
                width: `${w}%`, background: 'rgba(74,21,75,.1)',
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
            borderRadius: 12, border: '1px solid rgba(74,21,75,.15)',
            background: 'rgba(74,21,75,.03)', overflow: 'hidden',
          }}>
            <div style={{
              padding: '9px 16px 8px', borderBottom: '1px solid rgba(74,21,75,.1)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={SLACK_COLOR} strokeWidth="2.5" strokeLinecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: SLACK_COLOR }}>
                Sync metadata
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', padding: '12px 16px 16px' }}>
              {Array.isArray(metrics?.channels) && metrics.channels.length > 0 && (
                <div style={{ flex: '1 1 100%', padding: '0 0 10px', borderBottom: '1px solid rgba(74,21,75,.1)', marginBottom: 10 }}>
                  <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600, marginBottom: 6 }}>
                    {metrics.channels.length === 1 ? 'Channel' : 'Channels'}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {metrics.channels.map(ch => (
                      <span key={ch.id ?? ch.name} style={{
                        fontSize: 11.5, fontWeight: 700, color: SLACK_COLOR,
                        background: 'rgba(74,21,75,.08)', border: '1px solid rgba(74,21,75,.18)',
                        borderRadius: 6, padding: '2px 8px',
                      }}>
                        #{ch.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div style={{
                flex: '1 1 120px',
                padding: '4px 14px 4px 0',
                borderRight: metrics?.last_synced_at ? '1px solid rgba(74,21,75,.1)' : 'none',
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

      <div style={{ padding: '0 22px 16px 80px' }}>
        {!showCreateChannel ? (
          <button
            type="button"
            onClick={() => { setShowCreateChannel(true); setChannelName(oid); setOrchestrateResult(null); setOrchestrateErr(null) }}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              padding: '5px 12px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              cursor: 'pointer', border: '1.5px solid rgba(74,21,75,.35)',
              background: 'transparent', color: SLACK_COLOR, fontFamily: 'var(--font)',
              transition: 'opacity .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.7' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1' }}
          >
            + Create Channel
          </button>
        ) : (
          <div style={{
            borderRadius: 12, border: '1px solid rgba(74,21,75,.18)',
            background: 'rgba(74,21,75,.03)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase', color: SLACK_COLOR }}>
                Create Channel
              </span>
              <button
                type="button"
                onClick={() => setShowCreateChannel(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, color: '#94A3B8', lineHeight: 1 }}
              >×</button>
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: 'block', fontSize: 10.5, fontWeight: 700, color: '#64748B', marginBottom: 3 }}>
                Channel name
              </label>
              <input
                type="text"
                value={channelName}
                onChange={e => setChannelName(e.target.value)}
                placeholder={oid}
                style={{
                  width: '100%', boxSizing: 'border-box',
                  padding: '6px 10px', borderRadius: 8, fontSize: 12,
                  border: '1.5px solid rgba(74,21,75,.2)', outline: 'none',
                  fontFamily: 'var(--font)', color: NAVY, background: '#fff',
                }}
              />
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ display: 'block', fontSize: 10.5, fontWeight: 700, color: '#64748B', marginBottom: 3 }}>
                Team emails (comma-separated)
              </label>
              <textarea
                value={teamEmailsInput}
                onChange={e => setTeamEmailsInput(e.target.value)}
                placeholder="user@example.com, user2@example.com"
                rows={2}
                style={{
                  width: '100%', boxSizing: 'border-box',
                  padding: '6px 10px', borderRadius: 8, fontSize: 12,
                  border: '1.5px solid rgba(74,21,75,.2)', outline: 'none',
                  fontFamily: 'var(--font)', color: NAVY, background: '#fff',
                  resize: 'vertical',
                }}
              />
            </div>

            <button
              type="button"
              disabled={orchestrateBusy}
              onClick={() => void handleCreateChannel()}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '7px 16px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                cursor: orchestrateBusy ? 'not-allowed' : 'pointer',
                border: `1.5px solid ${SLACK_COLOR}`,
                background: SLACK_COLOR, color: '#fff',
                fontFamily: 'var(--font)', opacity: orchestrateBusy ? 0.55 : 1,
                transition: 'opacity .12s',
              }}
            >
              {orchestrateBusy && <SpinIcon size={11} />}
              {orchestrateBusy ? 'Creating…' : 'Create'}
            </button>

            {orchestrateResult && (
              <div style={{ marginTop: 8, fontSize: 11, color: '#0F766E', fontWeight: 600 }}>
                {orchestrateResult.message ?? 'Channel created successfully!'}
              </div>
            )}
            {orchestrateErr && (
              <div style={{ marginTop: 8, fontSize: 11, color: '#DC2626' }}>{orchestrateErr}</div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
