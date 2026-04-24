import { useCallback, useEffect, useRef, useState } from 'react'
import {
  listTeamUsers,
  createTeam,
  assignOpportunities,
  listUnassignedOpportunities,
} from '../services/teamsApi'

const PRIMARY = '#0B3C5D'
const ACCENT = '#F28C28'

function Avatar({ name, size = 28 }) {
  const initials = String(name || '')
    .trim().split(' ').filter(Boolean).slice(0, 2)
    .map(p => p[0].toUpperCase()).join('') || '?'
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      background: `linear-gradient(135deg, ${PRIMARY}, #1a5276)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.37, fontWeight: 800, color: '#fff', letterSpacing: '.03em',
    }}>
      {initials}
    </div>
  )
}

export default function AddTeamModal({ onClose, onCreated }) {
  const [teamName, setTeamName] = useState('')

  const [users, setUsers] = useState([])
  const [loadingUsers, setLoadingUsers] = useState(true)
  const [selectedMembers, setSelectedMembers] = useState(new Set())
  const [leadIds, setLeadIds] = useState(new Set())
  const [memberSearch, setMemberSearch] = useState('')

  const [opportunities, setOpportunities] = useState([])
  const [loadingOpps, setLoadingOpps] = useState(true)
  const [selectedOpps, setSelectedOpps] = useState(new Set())
  const [oppSearch, setOppSearch] = useState('')

  const [busy, setBusy] = useState(false)
  const [busyMsg, setBusyMsg] = useState('')
  const [error, setError] = useState(null)
  const nameRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setLoadingUsers(true)
    listTeamUsers()
      .then(data => { if (!cancelled) setUsers(data) })
      .catch(() => { if (!cancelled) setUsers([]) })
      .finally(() => { if (!cancelled) setLoadingUsers(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoadingOpps(true)
    listUnassignedOpportunities()
      .then(data => { if (!cancelled) setOpportunities(data) })
      .catch(() => { if (!cancelled) setOpportunities([]) })
      .finally(() => { if (!cancelled) setLoadingOpps(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => { nameRef.current?.focus() }, [])

  const toggleMember = useCallback((id) => {
    setSelectedMembers(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
        setLeadIds(l => { const nl = new Set(l); nl.delete(id); return nl })
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const toggleLead = useCallback((id) => {
    setLeadIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) }
      else { if (next.size >= 2) return prev; next.add(id) }
      return next
    })
  }, [])

  const toggleOpp = useCallback((id) => {
    setSelectedOpps(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const filteredUsers = users.filter(u => {
    const q = memberSearch.toLowerCase()
    const name = String(u.name || u.display_name || u.email || '').toLowerCase()
    const email = String(u.email || '').toLowerCase()
    return name.includes(q) || email.includes(q)
  })

  const filteredOpps = opportunities.filter(o => {
    const q = oppSearch.toLowerCase()
    const name = String(o.name || o.opportunity_id || '').toLowerCase()
    return name.includes(q)
  })

  const isValid = teamName.trim().length > 0 && selectedMembers.size > 0

  const handleSubmit = async () => {
    const name = teamName.trim()
    if (!name) { setError('Team name is required.'); return }
    if (selectedMembers.size === 0) { setError('Select at least one member.'); return }

    setBusy(true)
    setError(null)

    // Step 1: Create team with members
    let teamId
    try {
      setBusyMsg('Creating team…')
      const members = [...selectedMembers].map(uid => ({
        user_id: uid,
        is_lead: leadIds.has(uid),
      }))
      const result = await createTeam({ name, members })
      teamId = result.id ?? result.team_id
    } catch (e) {
      setError(e?.message || 'Failed to create team.')
      setBusy(false)
      setBusyMsg('')
      return
    }

    // Step 2: Assign opportunities (if any selected)
    if (selectedOpps.size > 0 && teamId) {
      try {
        setBusyMsg('Assigning opportunities…')
        await assignOpportunities(teamId, [...selectedOpps], { allowReassignment: true })
      } catch {
        // Opp assignment failed but team was created — still close and refresh
      }
    }

    setBusy(false)
    setBusyMsg('')
    onCreated()
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    padding: '8px 12px', borderRadius: 8, fontSize: 12,
    border: '1px solid #e2e8f0', outline: 'none',
    fontFamily: 'inherit', color: '#1e293b',
    marginBottom: 8,
  }

  const listContainerStyle = {
    flex: 1, overflowY: 'auto',
    border: '1px solid #edf2f7', borderRadius: 10,
    minHeight: 0,
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 300,
        background: 'rgba(15,23,42,.45)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', borderRadius: 16, width: '100%', maxWidth: 740,
        maxHeight: 'calc(100vh - 48px)',
        boxShadow: '0 20px 60px rgba(15,23,42,.18)',
        fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* ── Header ───────────────────────────────────── */}
        <div style={{
          padding: '24px 28px 20px',
          borderBottom: '1px solid #edf2f7',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: PRIMARY }}>
            Add New Team
          </h3>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 20, color: '#94a3b8', padding: 4, lineHeight: 1,
            }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* ── Body ─────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 28px 24px', minHeight: 0 }}>
          {/* Team Name */}
          <label style={{ display: 'block', marginBottom: 20 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: PRIMARY, display: 'block', marginBottom: 6 }}>
              Team Name
            </span>
            <input
              ref={nameRef}
              value={teamName}
              onChange={e => { setTeamName(e.target.value); setError(null) }}
              placeholder="Enter team name"
              maxLength={100}
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '10px 12px', borderRadius: 8, fontSize: 13,
                border: '1px solid #e2e8f0', outline: 'none',
                fontFamily: 'inherit', color: '#1e293b',
                transition: 'border-color .15s',
              }}
              onFocus={e => { e.target.style.borderColor = PRIMARY }}
              onBlur={e => { e.target.style.borderColor = '#e2e8f0' }}
            />
          </label>

          {/* Two-column layout */}
          <div style={{ display: 'flex', gap: 20, minHeight: 340 }}>

            {/* ── LEFT: Opportunities ───────────────── */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginBottom: 8,
              }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: PRIMARY }}>
                  Select Opportunities
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>
                  {selectedOpps.size} selected
                </span>
              </div>

              <input
                value={oppSearch}
                onChange={e => setOppSearch(e.target.value)}
                placeholder="Search opportunities…"
                style={inputStyle}
              />

              {loadingOpps ? (
                <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                  Loading…
                </div>
              ) : filteredOpps.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                  {opportunities.length === 0 ? 'No unassigned opportunities' : 'No matches'}
                </div>
              ) : (
                <div style={listContainerStyle}>
                  {filteredOpps.map(o => {
                    const oid = o.id ?? o.opportunity_id
                    const name = o.name || o.opportunity_id || 'Unnamed'
                    const isSelected = selectedOpps.has(oid)
                    return (
                      <div
                        key={oid}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '10px 12px',
                          borderBottom: '1px solid #f1f5f9',
                          background: isSelected ? 'rgba(11,60,93,.04)' : 'transparent',
                          cursor: 'pointer', transition: 'background .1s',
                        }}
                        onClick={() => toggleOpp(oid)}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          readOnly
                          style={{ accentColor: PRIMARY, cursor: 'pointer', flexShrink: 0 }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{
                            fontSize: 13, fontWeight: 600, color: '#1e293b',
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          }}>
                            {name}
                          </div>
                          {o.status && (
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>
                              {o.status}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* ── RIGHT: Members ────────────────────── */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginBottom: 8,
              }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: PRIMARY }}>
                  Select Members
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>
                  {selectedMembers.size} selected · {leadIds.size}/2 leads
                </span>
              </div>

              <input
                value={memberSearch}
                onChange={e => setMemberSearch(e.target.value)}
                placeholder="Search users…"
                style={inputStyle}
              />

              {loadingUsers ? (
                <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                  Loading…
                </div>
              ) : filteredUsers.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                  No users found
                </div>
              ) : (
                <div style={listContainerStyle}>
                  {filteredUsers.map(u => {
                    const uid = u.id ?? u.user_id ?? u.uid
                    const name = u.name || u.display_name || u.email || 'Unknown'
                    const isSelected = selectedMembers.has(uid)
                    const isLead = leadIds.has(uid)
                    return (
                      <div
                        key={uid}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          padding: '9px 12px',
                          borderBottom: '1px solid #f1f5f9',
                          background: isSelected ? 'rgba(11,60,93,.04)' : 'transparent',
                          cursor: 'pointer', transition: 'background .1s',
                        }}
                        onClick={() => toggleMember(uid)}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          readOnly
                          style={{ accentColor: PRIMARY, cursor: 'pointer', flexShrink: 0 }}
                        />
                        <Avatar name={name} size={26} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{
                            fontSize: 12, fontWeight: 600, color: '#1e293b',
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          }}>
                            {name}
                          </div>
                          {u.email && (
                            <div style={{
                              fontSize: 10, color: '#94a3b8',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}>
                              {u.email}
                            </div>
                          )}
                        </div>
                        {isSelected && (
                          <button
                            onClick={(e) => { e.stopPropagation(); toggleLead(uid) }}
                            style={{
                              padding: '2px 8px', borderRadius: 10, fontSize: 9, fontWeight: 700,
                              cursor: 'pointer', transition: 'all .15s', flexShrink: 0,
                              border: isLead ? `1.5px solid ${ACCENT}` : '1.5px solid #cbd5e1',
                              background: isLead ? 'rgba(242,140,40,.1)' : 'transparent',
                              color: isLead ? ACCENT : '#94a3b8',
                              letterSpacing: '.02em',
                            }}
                            title={leadIds.size >= 2 && !isLead ? 'Max 2 leads allowed' : ''}
                          >
                            {isLead ? '★ Lead' : 'Set Lead'}
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Footer ───────────────────────────────────── */}
        <div style={{
          padding: '16px 28px', borderTop: '1px solid #edf2f7',
          display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'space-between',
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {error && (
              <p style={{ margin: 0, fontSize: 12, color: '#dc2626', fontWeight: 500 }}>{error}</p>
            )}
            {busy && busyMsg && (
              <p style={{ margin: 0, fontSize: 12, color: '#64748b', fontWeight: 500 }}>{busyMsg}</p>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
            <button
              onClick={onClose}
              disabled={busy}
              style={{
                padding: '9px 20px', borderRadius: 8,
                border: '1px solid #e2e8f0', background: '#f8fafc',
                color: '#64748b', fontWeight: 600, fontSize: 13,
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={busy || !isValid}
              style={{
                padding: '9px 22px', borderRadius: 8, border: 'none',
                background: (!isValid && !busy) ? '#94a3b8' : PRIMARY,
                color: '#fff', fontWeight: 700, fontSize: 13,
                cursor: (busy || !isValid) ? 'not-allowed' : 'pointer',
                opacity: busy ? 0.7 : 1,
                fontFamily: 'inherit',
                boxShadow: isValid ? '0 2px 8px rgba(11,60,93,.2)' : 'none',
                transition: 'background .15s',
              }}
            >
              {busy ? 'Creating…' : 'Create Team'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
