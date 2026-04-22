import { useCallback, useEffect, useRef, useState } from 'react'
import { listOpportunityRequests, reviewOpportunityRequest } from '../services/requestsApi'

const SI_NAVY = '#1B264F'
const SI_ORANGE = '#E8532E'

const STATUS_META = {
  PENDING:  { bg: 'rgba(234,179,8,.1)',      text: '#854d0e', border: 'rgba(234,179,8,.3)',      dot: '#d97706' },
  APPROVED: { bg: 'rgba(5,150,105,.1)',       text: '#065f46', border: 'rgba(5,150,105,.25)',     dot: '#059669' },
  REJECTED: { bg: 'rgba(220,38,38,.08)',      text: '#991b1b', border: 'rgba(220,38,38,.2)',      dot: '#dc2626' },
}

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.PENDING
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
      background: m.bg, color: m.text, border: `1px solid ${m.border}`,
      letterSpacing: '0.04em', textTransform: 'uppercase',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: m.dot, flexShrink: 0 }} />
      {status}
    </span>
  )
}

function Avatar({ name }) {
  const initials = String(name || '')
    .trim()
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(p => p[0].toUpperCase())
    .join('') || '?'
  return (
    <div style={{
      width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
      background: `linear-gradient(135deg, ${SI_NAVY}, #2d4a8a)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 11, fontWeight: 800, color: '#fff', letterSpacing: '.03em',
    }}>
      {initials}
    </div>
  )
}

function ReviewModal({ request, onClose, onDone }) {
  const [action, setAction] = useState('APPROVED')
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async () => {
    if (action === 'REJECTED' && !remarks.trim()) {
      setError('Remarks are required when rejecting.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await reviewOpportunityRequest({
        request_id: request.request_id,
        status: action,
        admin_remarks: remarks.trim() || null,
      })
      onDone()
    } catch (e) {
      const status = e?.status
      let msg = e?.message || 'Failed to submit review.'
      if (status === 409) msg = 'This request has already been reviewed.'
      else if (status === 404) msg = 'Request not found.'
      else if (status === 503) msg = 'Could not allocate a unique opportunity ID right now. Please retry.'
      setError(msg)
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 300,
        background: 'rgba(15,23,42,.45)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', borderRadius: 16, padding: 28, width: '100%', maxWidth: 480,
        boxShadow: '0 20px 60px rgba(15,23,42,.18)',
        fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
      }}>
        <h3 style={{ margin: '0 0 4px', fontSize: 16, fontWeight: 700, color: SI_NAVY }}>
          Review Request
        </h3>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: '#64748b' }}>
          <strong style={{ color: SI_NAVY }}>{request.opportunity_title}</strong>
          <span style={{ marginLeft: 8, opacity: .6, fontStyle: 'italic' }}>
            by {request.user_name || `User #${request.user_id}`}
          </span>
        </p>

        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          {['APPROVED', 'REJECTED'].map(a => (
            <button key={a} onClick={() => setAction(a)} style={{
              flex: 1, padding: '9px 0', borderRadius: 8, fontWeight: 700, fontSize: 13,
              cursor: 'pointer', transition: 'all .15s',
              border: action === a
                ? `2px solid ${a === 'APPROVED' ? '#059669' : SI_ORANGE}`
                : '2px solid #e2e8f0',
              background: action === a
                ? (a === 'APPROVED' ? 'rgba(5,150,105,.08)' : 'rgba(232,83,46,.07)')
                : '#f8fafc',
              color: action === a
                ? (a === 'APPROVED' ? '#065f46' : SI_ORANGE)
                : '#64748b',
            }}>
              {a === 'APPROVED' ? '✓ Approve' : '✕ Reject'}
            </button>
          ))}
        </div>

        <textarea
          placeholder={action === 'REJECTED' ? 'Remarks (required)' : 'Remarks (optional)'}
          value={remarks}
          onChange={e => setRemarks(e.target.value)}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'vertical',
            padding: '10px 12px', borderRadius: 8, fontSize: 13,
            border: '1px solid #e2e8f0', outline: 'none',
            fontFamily: 'inherit', color: '#1e293b',
          }}
        />

        {error && <p style={{ margin: '8px 0 0', fontSize: 12, color: SI_ORANGE }}>{error}</p>}

        <div style={{ display: 'flex', gap: 10, marginTop: 18, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={busy} style={{
            padding: '9px 20px', borderRadius: 8, border: '1px solid #e2e8f0',
            background: '#f8fafc', color: '#64748b', fontWeight: 600, fontSize: 13,
            cursor: 'pointer', fontFamily: 'inherit',
          }}>
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={busy} style={{
            padding: '9px 22px', borderRadius: 8, border: 'none',
            background: action === 'APPROVED' ? '#059669' : SI_ORANGE,
            color: '#fff', fontWeight: 700, fontSize: 13,
            cursor: busy ? 'not-allowed' : 'pointer', opacity: busy ? .7 : 1,
            fontFamily: 'inherit',
          }}>
            {busy ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  )
}

function RequestCard({ r, onReview }) {
  const submitted = new Date(r.submitted_at)
  const dateStr = submitted.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  const timeStr = submitted.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  const isPending = r.status === 'PENDING'

  return (
    <div style={{
      background: '#fff',
      borderRadius: 14,
      border: `1px solid ${isPending ? 'rgba(234,179,8,.25)' : 'rgba(27,38,79,.08)'}`,
      boxShadow: isPending
        ? '0 2px 12px rgba(234,179,8,.08)'
        : '0 1px 4px rgba(15,23,42,.05)',
      padding: '20px 20px 18px',
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      transition: 'box-shadow .15s',
    }}>
      {/* Top row: title + badge */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
        <h3 style={{
          margin: 0, fontSize: 14, fontWeight: 700, color: SI_NAVY,
          lineHeight: 1.35, flex: 1, wordBreak: 'break-word',
        }}>
          {r.opportunity_title}
        </h3>
        <StatusBadge status={r.status} />
      </div>

      {/* Requester */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <Avatar name={r.user_name || String(r.user_id)} />
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', lineHeight: 1.2 }}>
            {r.user_name || `User #${r.user_id}`}
          </div>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
            {dateStr} · {timeStr}
          </div>
        </div>
      </div>

      {/* Remarks (if any) */}
      {r.admin_remarks && (
        <div style={{
          padding: '9px 12px', borderRadius: 8,
          background: r.status === 'REJECTED' ? 'rgba(220,38,38,.05)' : 'rgba(5,150,105,.05)',
          border: `1px solid ${r.status === 'REJECTED' ? 'rgba(220,38,38,.12)' : 'rgba(5,150,105,.12)'}`,
          fontSize: 12, color: '#475569', lineHeight: 1.5,
        }}>
          <span style={{ fontWeight: 700, fontSize: 10, letterSpacing: '.05em', textTransform: 'uppercase', color: '#94a3b8', display: 'block', marginBottom: 3 }}>Admin remarks</span>
          {r.admin_remarks}
        </div>
      )}

      {/* Action */}
      {isPending ? (
        <button
          onClick={() => onReview(r)}
          style={{
            marginTop: 'auto',
            padding: '9px 0', borderRadius: 9,
            border: `1.5px solid ${SI_NAVY}`,
            background: 'transparent', color: SI_NAVY,
            fontWeight: 700, fontSize: 12, cursor: 'pointer',
            fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
            width: '100%', transition: 'background .15s, color .15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = SI_NAVY; e.currentTarget.style.color = '#fff' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = SI_NAVY }}
        >
          Review
        </button>
      ) : (
        <div style={{
          marginTop: 'auto', padding: '9px 0', borderRadius: 9, textAlign: 'center',
          background: '#f8fafc', border: '1px solid #e2e8f0',
          fontSize: 12, fontWeight: 600,
          color: r.status === 'APPROVED' ? '#059669' : '#dc2626',
        }}>
          {r.status === 'APPROVED' ? '✓ Approved' : '✕ Rejected'}
        </div>
      )}
    </div>
  )
}

export default function AdminRequestsPage({ onBack }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [reviewing, setReviewing] = useState(null)
  const [toastMsg, setToastMsg] = useState(null)
  const toastTimer = useRef(null)

  const showToast = useCallback((msg) => {
    setToastMsg(msg)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToastMsg(null), 4000)
  }, [])

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const data = await listOpportunityRequests()
      setRequests(data)
    } catch (e) {
      setError(e?.message || 'Failed to load requests.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleReviewDone = () => {
    setReviewing(null)
    showToast('Review submitted successfully.')
    load(true)
  }

  const filteredRequests = filterStatus === 'ALL'
    ? requests
    : requests.filter(r => r.status === filterStatus)

  const counts = {
    ALL: requests.length,
    PENDING: requests.filter(r => r.status === 'PENDING').length,
    APPROVED: requests.filter(r => r.status === 'APPROVED').length,
    REJECTED: requests.filter(r => r.status === 'REJECTED').length,
  }

  return (
    <div style={{
      minHeight: 'calc(100vh - 56px)',
      background: 'var(--bg, #f4f6f9)',
      padding: '24px 20px 48px',
      fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
    }}>
      <div style={{ maxWidth: 1040, margin: '0 auto' }}>

        {/* Back */}
        <button onClick={onBack} style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '8px 4px 8px 0', border: 'none', background: 'none',
          cursor: 'pointer', fontSize: 13, fontWeight: 600,
          color: 'var(--text2)', marginBottom: 20, fontFamily: 'inherit',
        }}>
          <span aria-hidden style={{ fontSize: 16 }}>←</span>
          Back
        </button>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 22, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: SI_NAVY }}>
              Opportunity Requests
            </h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b' }}>
              Review and act on pending opportunity creation requests.
            </p>
          </div>
          <button onClick={() => load()} style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 16px', borderRadius: 8, border: '1px solid #e2e8f0',
            background: '#fff', color: SI_NAVY, fontWeight: 600, fontSize: 13,
            cursor: 'pointer', fontFamily: 'inherit',
          }}>
            ↺ Refresh
          </button>
        </div>

        {/* Filter tabs */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 22, flexWrap: 'wrap' }}>
          {['ALL', 'PENDING', 'APPROVED', 'REJECTED'].map(s => (
            <button key={s} onClick={() => setFilterStatus(s)} style={{
              padding: '6px 14px', borderRadius: 20, fontSize: 12, fontWeight: 700,
              cursor: 'pointer',
              border: filterStatus === s ? `1.5px solid ${SI_NAVY}` : '1.5px solid #e2e8f0',
              background: filterStatus === s ? SI_NAVY : '#fff',
              color: filterStatus === s ? '#fff' : '#64748b',
              fontFamily: 'inherit',
            }}>
              {s}&nbsp;<span style={{ opacity: .65 }}>({counts[s]})</span>
            </button>
          ))}
        </div>

        {/* States */}
        {loading && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 16,
          }}>
            {[1,2,3].map(i => (
              <div key={i} style={{
                background: '#fff', borderRadius: 14, border: '1px solid rgba(27,38,79,.08)',
                padding: '20px', height: 180,
                animation: 'skPulse 1.5s ease-in-out infinite',
                animationDelay: `${i * .1}s`,
              }} />
            ))}
            <style>{`@keyframes skPulse{0%,100%{opacity:1}50%{opacity:.45}}`}</style>
          </div>
        )}

        {!loading && error && (
          <div style={{
            background: '#fff', borderRadius: 14,
            border: '1px solid rgba(220,38,38,.15)',
            padding: '20px 24px', color: SI_ORANGE, fontSize: 13,
          }}>
            {error}
          </div>
        )}

        {!loading && !error && filteredRequests.length === 0 && (
          <div style={{
            background: '#fff', borderRadius: 14,
            border: '1px solid rgba(27,38,79,.08)',
            padding: '56px 24px', textAlign: 'center',
            color: '#94a3b8', fontSize: 14,
          }}>
            No {filterStatus === 'ALL' ? '' : filterStatus.toLowerCase() + ' '}requests found.
          </div>
        )}

        {!loading && !error && filteredRequests.length > 0 && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(288px, 1fr))',
            gap: 16,
            alignItems: 'start',
          }}>
            {filteredRequests.map(r => (
              <RequestCard key={r.request_id} r={r} onReview={setReviewing} />
            ))}
          </div>
        )}
      </div>

      {reviewing && (
        <ReviewModal
          request={reviewing}
          onClose={() => setReviewing(null)}
          onDone={handleReviewDone}
        />
      )}

      {toastMsg && (
        <div style={{
          position: 'fixed', bottom: 28, left: '50%', transform: 'translateX(-50%)',
          background: SI_NAVY, color: '#fff', padding: '12px 22px', borderRadius: 10,
          fontSize: 13, fontWeight: 600, boxShadow: '0 8px 24px rgba(15,23,42,.25)',
          zIndex: 400, pointerEvents: 'none', whiteSpace: 'nowrap',
          fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
        }}>
          {toastMsg}
        </div>
      )}
    </div>
  )
}