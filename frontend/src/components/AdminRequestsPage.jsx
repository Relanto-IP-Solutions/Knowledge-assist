import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { listOpportunityRequests, reviewOpportunityRequest } from '../services/requestsApi'

const SI_NAVY = '#1B264F'
const SI_ORANGE = '#E8532E'

const STATUS_META = {
  PENDING:  { bg: 'rgba(234,179,8,.1)',  text: '#854d0e', border: 'rgba(234,179,8,.3)',  dot: '#d97706' },
  APPROVED: { bg: 'rgba(5,150,105,.1)',   text: '#065f46', border: 'rgba(5,150,105,.25)', dot: '#059669' },
  REJECTED: { bg: 'rgba(220,38,38,.08)', text: '#991b1b', border: 'rgba(220,38,38,.2)',  dot: '#dc2626' },
}

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.PENDING
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
      background: m.bg, color: m.text, border: `1px solid ${m.border}`,
      letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap',
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

/* ── Stat Card ─────────────────────────────────────────────── */
function StatCard({ icon, value, label, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 1, minWidth: 160,
        display: 'flex', alignItems: 'center', gap: 14,
        padding: '18px 20px', borderRadius: 14,
        border: active ? `2px solid ${SI_NAVY}` : '1px solid rgba(27,38,79,.10)',
        background: '#fff', cursor: 'pointer',
        boxShadow: active ? '0 2px 12px rgba(27,38,79,.08)' : '0 1px 4px rgba(15,23,42,.04)',
        fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
        transition: 'all .15s',
      }}
    >
      <div style={{
        width: 42, height: 42, borderRadius: 10, flexShrink: 0,
        background: icon.bg, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {icon.el}
      </div>
      <div style={{ textAlign: 'left' }}>
        <div style={{ fontSize: 24, fontWeight: 800, color: SI_NAVY, lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginTop: 2 }}>{label}</div>
      </div>
    </button>
  )
}

/* ── Review Modal ──────────────────────────────────────────── */
function ReviewModal({ request, onClose, onDone, mode }) {
  const isReconsider = mode === 'reconsider'
  const [action, setAction] = useState(isReconsider ? 'APPROVED' : 'APPROVED')
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
          {isReconsider ? 'Reconsider Request' : 'Review Request'}
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

/* ── Common action button style ────────────────────────────── */
const actionBtnBase = {
  padding: '8px 0',
  width: 110,
  borderRadius: 8,
  fontWeight: 700,
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: 'inherit',
  whiteSpace: 'nowrap',
  textAlign: 'center',
  display: 'inline-block',
  boxSizing: 'border-box',
}

/* ── View Detail Modal ─────────────────────────────────────── */
function ViewDetailModal({ request, onClose }) {
  if (!request) return null
  const submitted = new Date(request.submitted_at)
  const dateStr = submitted.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  const timeStr = submitted.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })

  const rows = [
    { label: 'Request ID', value: request.request_id },
    { label: 'Opportunity Title', value: request.opportunity_title },
    { label: 'Opportunity ID', value: request.opportunity_id || '—' },
    { label: 'Requested By', value: request.user_name || `User #${request.user_id}` },
    { label: 'User ID', value: request.user_id },
    { label: 'User Email', value: request.user_email || '—' },
    { label: 'Status', value: request.status, badge: true },
    { label: 'Submitted On', value: `${dateStr} at ${timeStr}` },
    { label: 'Admin Remarks', value: request.admin_remarks || '—' },
    { label: 'Reviewed By', value: request.reviewed_by || request.admin_name || '—' },
    { label: 'Reviewed On', value: request.reviewed_at ? new Date(request.reviewed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) + ' at ' + new Date(request.reviewed_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '—' },
  ]

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
        background: '#fff', borderRadius: 16, padding: 0, width: '100%', maxWidth: 520,
        boxShadow: '0 20px 60px rgba(15,23,42,.18)',
        fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 28px 16px',
          borderBottom: '1px solid rgba(27,38,79,.08)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: SI_NAVY }}>
              Request Details
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: '#94a3b8' }}>
              Full details for this opportunity request
            </p>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#94a3b8', fontSize: 20, padding: '4px 8px', lineHeight: 1,
          }}>✕</button>
        </div>

        {/* Detail rows */}
        <div style={{ padding: '8px 28px 24px', maxHeight: 420, overflowY: 'auto' }}>
          {rows.map(row => {
            const val = row.value
            if (val == null || val === undefined) return null
            return (
              <div key={row.label} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                padding: '12px 0',
                borderBottom: '1px solid rgba(27,38,79,.05)',
                gap: 16,
              }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: '#64748b', flexShrink: 0, minWidth: 120 }}>
                  {row.label}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', textAlign: 'right', wordBreak: 'break-all' }}>
                  {row.badge ? <StatusBadge status={String(val)} /> : String(val)}
                </span>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div style={{ padding: '14px 28px', borderTop: '1px solid rgba(27,38,79,.08)', textAlign: 'right' }}>
          <button onClick={onClose} style={{
            padding: '9px 24px', borderRadius: 8, border: '1px solid #e2e8f0',
            background: '#f8fafc', color: '#64748b', fontWeight: 600, fontSize: 13,
            cursor: 'pointer', fontFamily: 'inherit',
          }}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Stat Icons ────────────────────────────────────────────── */
const iconTotal = {
  bg: 'rgba(27,38,79,.06)',
  el: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={SI_NAVY} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>,
}
const iconPending = {
  bg: 'rgba(234,179,8,.1)',
  el: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
}
const iconApproved = {
  bg: 'rgba(5,150,105,.1)',
  el: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>,
}
const iconRejected = {
  bg: 'rgba(220,38,38,.08)',
  el: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>,
}

/* ── Column header style ───────────────────────────────────── */
const thStyle = {
  padding: '12px 16px',
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  color: '#64748b',
  textAlign: 'left',
  borderBottom: '1px solid rgba(27,38,79,.10)',
  whiteSpace: 'nowrap',
}
const tdStyle = {
  padding: '14px 16px',
  fontSize: 13,
  color: '#1e293b',
  borderBottom: '1px solid rgba(27,38,79,.06)',
  verticalAlign: 'middle',
}

export default function AdminRequestsPage({ onBack }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [reviewing, setReviewing] = useState(null)
  const [reviewMode, setReviewMode] = useState('review')
  const [viewing, setViewing] = useState(null)
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

  const openReview = (r, mode = 'review') => {
    setReviewMode(mode)
    setReviewing(r)
  }

  return (
    <div style={{
      minHeight: 'calc(100vh - 56px)',
      background: 'var(--bg, #f4f6f9)',
      padding: '32px 64px 48px',
      fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
    }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* Breadcrumbs */}
        <nav aria-label="Breadcrumb" style={{ marginBottom: 18 }}>
          <ol style={{
            display: 'flex', alignItems: 'center', gap: 6,
            listStyle: 'none', margin: 0, padding: 0,
            fontSize: 11, fontWeight: 600, flexWrap: 'wrap',
          }}>
            {[
              { label: 'Knowledge Assist', to: '/knowledge-assist' },
              { label: 'Sales Intelligence', to: '/knowledge-assist' },
              { label: 'Admin Panel', to: null },
              { label: 'Opportunity Requests', to: null },
            ].map((crumb, index, arr) => {
              const isLast = index === arr.length - 1
              return (
                <li key={crumb.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {crumb.to && !isLast ? (
                    <Link
                      to={crumb.to}
                      style={{ color: 'rgba(77,85,119,.65)', fontWeight: 500, textDecoration: 'none', transition: 'color .15s' }}
                      onMouseEnter={e => { e.currentTarget.style.color = SI_NAVY }}
                      onMouseLeave={e => { e.currentTarget.style.color = 'rgba(77,85,119,.65)' }}
                    >
                      {crumb.label}
                    </Link>
                  ) : (
                    <span style={{ color: isLast ? SI_NAVY : 'rgba(77,85,119,.65)', fontWeight: isLast ? 700 : 500 }}>
                      {crumb.label}
                    </span>
                  )}
                  {!isLast && <span style={{ opacity: 0.45, fontSize: 10 }}>&gt;</span>}
                </li>
              )
            })}
          </ol>
        </nav>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: SI_NAVY }}>
              Opportunity Requests
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: 14, color: '#64748b' }}>
              Review and act on pending opportunity creation requests.
            </p>
          </div>
          <button onClick={() => load()} style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '10px 20px', borderRadius: 10, border: '1px solid #e2e8f0',
            background: '#fff', color: SI_NAVY, fontWeight: 600, fontSize: 13,
            cursor: 'pointer', fontFamily: 'inherit',
            boxShadow: '0 1px 3px rgba(15,23,42,.06)',
          }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
        </div>

        {/* Stat cards */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 28, flexWrap: 'wrap' }}>
          <StatCard icon={iconTotal}    value={counts.ALL}      label="Total Requests"  active={filterStatus === 'ALL'}      onClick={() => setFilterStatus('ALL')} />
          <StatCard icon={iconPending}  value={counts.PENDING}  label="Pending Review"  active={filterStatus === 'PENDING'}  onClick={() => setFilterStatus('PENDING')} />
          <StatCard icon={iconApproved} value={counts.APPROVED} label="Approved"         active={filterStatus === 'APPROVED'} onClick={() => setFilterStatus('APPROVED')} />
          <StatCard icon={iconRejected} value={counts.REJECTED} label="Rejected"         active={filterStatus === 'REJECTED'} onClick={() => setFilterStatus('REJECTED')} />
        </div>

        {/* Table */}
        {loading && (
          <div style={{
            background: '#fff', borderRadius: 14,
            border: '1px solid rgba(27,38,79,.08)',
            boxShadow: '0 1px 4px rgba(15,23,42,.04)',
            overflow: 'hidden',
          }}>
            <style>{`@keyframes shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}`}</style>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'inherit' }}>
              <thead>
                <tr style={{ background: '#FAFBFD' }}>
                  {['Opportunity', 'Requested By', 'Requested On', 'Status', 'Admin Remarks', 'Action'].map((label, i) => (
                    <th key={i} style={{ ...thStyle, ...(i === 5 ? { textAlign: 'center' } : {}) }}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...Array(5)].map((_, idx) => (
                  <tr key={idx}>
                    {[150, 120, 90, 70, 100, 80].map((w, ci) => (
                      <td key={ci} style={{ ...tdStyle, ...(ci === 5 ? { textAlign: 'center' } : {}) }}>
                        <div style={{
                          height: 14, borderRadius: 6, width: w,
                          background: 'linear-gradient(90deg, #edf2f7 25%, #f8fafc 50%, #edf2f7 75%)',
                          backgroundSize: '800px 100%',
                          animation: 'shimmer 1.5s infinite linear',
                          ...(ci === 5 ? { margin: '0 auto' } : {}),
                        }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
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
            background: '#fff', borderRadius: 14,
            border: '1px solid rgba(27,38,79,.08)',
            boxShadow: '0 1px 4px rgba(15,23,42,.04)',
            overflow: 'hidden',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'inherit' }}>
              <thead>
                <tr style={{ background: '#FAFBFD' }}>
                  <th style={thStyle}>Opportunity</th>
                  <th style={thStyle}>Requested By</th>
                  <th style={thStyle}>Requested On</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle}>Admin Remarks</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredRequests.map(r => {
                  const submitted = new Date(r.submitted_at)
                  const dateStr = submitted.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                  const timeStr = submitted.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
                  const isPending = r.status === 'PENDING'
                  const isRejected = r.status === 'REJECTED'
                  const isApproved = r.status === 'APPROVED'

                  return (
                    <tr key={r.request_id} style={{ transition: 'background .12s' }}
                      onMouseEnter={e => { e.currentTarget.style.background = '#FAFBFD' }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                    >
                      {/* Opportunity */}
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div style={{
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                            background: 'rgba(27,38,79,.05)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                          }}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                          </div>
                          <span style={{ fontWeight: 600, color: SI_NAVY }}>{r.opportunity_title}</span>
                        </div>
                      </td>
                      {/* Requested By */}
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                          <Avatar name={r.user_name || String(r.user_id)} />
                          <span style={{ fontWeight: 600 }}>{r.user_name || `User #${r.user_id}`}</span>
                        </div>
                      </td>
                      {/* Requested On */}
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b' }}>{dateStr}</div>
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>{timeStr}</div>
                          </div>
                        </div>
                      </td>
                      {/* Status */}
                      <td style={tdStyle}><StatusBadge status={r.status} /></td>
                      {/* Admin Remarks */}
                      <td style={{ ...tdStyle, color: r.admin_remarks ? '#475569' : '#cbd5e1', fontSize: 12 }}>
                        {r.admin_remarks || '—'}
                      </td>
                      {/* Action */}
                      <td style={{ ...tdStyle, textAlign: 'center' }}>
                        {isPending && (
                          <button
                            onClick={() => openReview(r, 'review')}
                            style={{
                              ...actionBtnBase,
                              border: 'none',
                              background: SI_NAVY, color: '#fff',
                            }}
                          >
                            Review
                          </button>
                        )}
                        {isApproved && (
                          <button
                            onClick={() => setViewing(r)}
                            style={{
                              ...actionBtnBase,
                              border: '1.5px solid rgba(27,38,79,.18)',
                              background: '#fff', color: SI_NAVY,
                            }}
                          >
                            View
                          </button>
                        )}
                        {isRejected && (
                          <button
                            onClick={() => setViewing(r)}
                            style={{
                              ...actionBtnBase,
                              border: '1.5px solid rgba(27,38,79,.18)',
                              background: '#fff', color: SI_NAVY,
                            }}
                          >
                            View
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {reviewing && (
        <ReviewModal
          request={reviewing}
          mode={reviewMode}
          onClose={() => setReviewing(null)}
          onDone={handleReviewDone}
        />
      )}

      {viewing && (
        <ViewDetailModal
          request={viewing}
          onClose={() => setViewing(null)}
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