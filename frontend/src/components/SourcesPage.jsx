import { useState, useCallback } from 'react'
import { toApiOpportunityId } from '../config/opportunityApi'
import GmailOpportunityCard from './GmailOpportunityCard'
import DriveOpportunityCard from './DriveOpportunityCard'
import SlackOpportunityCard from './SlackOpportunityCard'
import ZoomOpportunityCard from './ZoomOpportunityCard'
import OneDriveOpportunityCard from './OneDriveOpportunityCard'

/* ── design tokens ─────────────────────────────────────────────── */
const NAVY   = '#1B264F'
const ORANGE = '#E8532E'


/* ── SourcesPage ─────────────────────────────────────────────────── */
export default function SourcesPage({ opportunityId, opportunityName, onContinue, onBack }) {
  // Backend id used for all API calls (Zoom, answers, etc.)
  const apiOppId = toApiOpportunityId(opportunityId)


  // Per-service active map — updated only by the card that just connected/disconnected.
  // No API calls are made here. Each card self-manages its own status.
  const [activeServices, setActiveServices] = useState({
    drive:    false,
    gmail:    false,
    slack:    false,
    zoom:     false,
    onedrive: false,
  })

  // Called by each card when its connection state changes.
  // Only the card that fired the event updates the map — no cross-service side effects.
  const handleStatusChange = useCallback((service, isActive) => {
    setActiveServices(prev => {
      if (prev[service] === isActive) return prev   // no-op if unchanged
      return { ...prev, [service]: isActive }
    })
  }, [])

  const totalConnected = Object.values(activeServices).filter(Boolean).length
  const totalSources   = 5 // Drive, Gmail, Slack, Zoom, OneDrive

  return (
    <div style={{
      minHeight: 'calc(100vh - 56px)',
      background: '#F1F5F9',
      fontFamily: 'var(--font)',
      animation: 'fadeUp .2s ease',
      display: 'flex', flexDirection: 'column',
    }}>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={{
        background: `linear-gradient(135deg, ${NAVY} 0%, #263060 100%)`,
        padding: '12px 32px 14px',
        position: 'relative', overflow: 'hidden', flexShrink: 0,
      }}>
        <div style={{ position: 'relative', maxWidth: 920, margin: '0 auto', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          {/* Back button */}
          <button
            type="button" onClick={onBack}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '5px 10px 5px 7px', borderRadius: 6, border: 'none',
              background: 'rgba(255,255,255,.1)', color: 'rgba(255,255,255,.72)',
              cursor: 'pointer', fontSize: 11.5, fontWeight: 600, fontFamily: 'var(--font)',
              transition: 'background .12s', flexShrink: 0,
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,.18)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,.1)' }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
            Back
          </button>

          {/* Divider */}
          <span style={{ width: 1, height: 16, background: 'rgba(255,255,255,.15)', flexShrink: 0 }} />

          {/* Breadcrumb */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            fontSize: 9, fontWeight: 800, letterSpacing: '.1em', textTransform: 'uppercase',
            color: ORANGE, background: 'rgba(232,83,46,.12)', border: '1px solid rgba(232,83,46,.25)',
            borderRadius: 4, padding: '2px 7px', flexShrink: 0,
          }}>
            Step 1 of 2 — Connect Sources
          </div>

          {/* Title */}
          <h1 style={{
            fontSize: 14, fontWeight: 700, color: '#fff',
            margin: 0, letterSpacing: '-0.01em', flex: 1, minWidth: 0,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {opportunityName}
          </h1>

          {/* Connected pill */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 12px', borderRadius: 20,
            background: 'rgba(255,255,255,.08)', border: '1px solid rgba(255,255,255,.14)',
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#fff', lineHeight: 1 }}>{totalConnected}</span>
            <span style={{ fontSize: 11, color: 'rgba(255,255,255,.5)', fontWeight: 600 }}>/ {totalSources} connected</span>
          </div>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, maxWidth: 980, width: '100%', margin: '0 auto', padding: '28px 24px 48px', boxSizing: 'border-box' }}>
        <div style={{
          marginBottom: 14,
          padding: '10px 12px',
          borderRadius: 10,
          border: '1px solid rgba(27,38,79,.16)',
          background: 'rgba(27,38,79,.04)',
          color: NAVY,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
        }}>
          <span aria-hidden style={{ fontSize: 13, lineHeight: 1.3 }}>i</span>
          <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.5 }}>
            Use opportunity ID <strong>{apiOppId}</strong> for any conversation, prompts, or follow-up requests tied to this opportunity.
          </p>
        </div>

        {/* ── Source connector cards ───────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* Google Drive */}
          <div style={{
            background: '#fff', borderRadius: 16,
            border: '1.5px solid rgba(27,38,79,.09)',
            boxShadow: '0 1px 6px rgba(15,23,42,.04)',
            overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
          }}>
            <DriveOpportunityCard
              opportunityId={apiOppId}
              opportunityName={opportunityName}
              onStatusChange={(active) => handleStatusChange('drive', active)}
            />
          </div>

          {/* Gmail */}
          <div style={{
            background: '#fff', borderRadius: 16,
            border: '1.5px solid rgba(27,38,79,.09)',
            boxShadow: '0 1px 6px rgba(15,23,42,.04)',
            overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
          }}>
            <GmailOpportunityCard
              opportunityId={apiOppId}
              onStatusChange={(active) => handleStatusChange('gmail', active)}
            />
          </div>

          {/* Slack */}
          <div style={{
            background: '#fff', borderRadius: 16,
            border: '1.5px solid rgba(27,38,79,.09)',
            boxShadow: '0 1px 6px rgba(15,23,42,.04)',
            overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
          }}>
            <SlackOpportunityCard
              opportunityId={apiOppId}
              onStatusChange={(active) => handleStatusChange('slack', active)}
            />
          </div>

          {/* Zoom */}
          <div style={{
            background: '#fff', borderRadius: 16,
            border: '1.5px solid rgba(27,38,79,.09)',
            boxShadow: '0 1px 6px rgba(15,23,42,.04)',
            overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
          }}>
            <ZoomOpportunityCard
              opportunityId={apiOppId}
              onStatusChange={(active) => handleStatusChange('zoom', active)}
            />
          </div>

          {/* OneDrive */}
          <div style={{
            background: '#fff', borderRadius: 16,
            border: '1.5px solid rgba(27,38,79,.09)',
            boxShadow: '0 1px 6px rgba(15,23,42,.04)',
            overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
          }}>
            <OneDriveOpportunityCard
              opportunityId={apiOppId}
              onStatusChange={(active) => handleStatusChange('onedrive', active)}
            />
          </div>
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: 12, marginTop: 32,
        }}>
          <p style={{ fontSize: 12, color: 'var(--text3)', margin: 0, maxWidth: 400 }}>
            {totalConnected > 0
              ? `${totalConnected} source${totalConnected > 1 ? 's' : ''} connected. You can add more later.`
              : 'No sources connected yet. You can always connect them later.'}
          </p>
          <div style={{ display: 'flex', gap: 10 }}>
            <button type="button" onClick={onContinue}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '10px 14px', borderRadius: 9,
                border: '1px solid rgba(27,38,79,.2)', background: 'transparent', color: 'var(--text2)',
                fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)', transition: 'all .12s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(27,38,79,.05)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >Skip for now</button>
            <button type="button" onClick={onContinue}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '10px 22px', borderRadius: 9,
                border: 'none', background: NAVY, color: '#fff',
                fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font)',
                boxShadow: '0 2px 12px rgba(27,38,79,.22)', transition: 'background .12s, box-shadow .12s', whiteSpace: 'nowrap',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#263060'; e.currentTarget.style.boxShadow = '0 4px 18px rgba(27,38,79,.3)' }}
              onMouseLeave={e => { e.currentTarget.style.background = NAVY; e.currentTarget.style.boxShadow = '0 2px 12px rgba(27,38,79,.22)' }}
            >
              Continue to Q&A
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            </button>
          </div>
        </div>
      </div>

    </div>
  )
}
