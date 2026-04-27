import { useCallback, useEffect, useState } from 'react'
import { getTeam, listTeamUsers, updateTeam } from '../services/teamsApi'

const PRIMARY = '#0B3C5D'
const ACCENT = '#F28C28'

function Avatar({ name, size = 32 }) {
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

function RoleBadge({ isLead }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 9px', borderRadius: 12, fontSize: 10, fontWeight: 700,
      background: isLead ? 'rgba(242,140,40,.1)' : 'rgba(148,163,184,.1)',
      color: isLead ? ACCENT : '#64748b',
      border: `1px solid ${isLead ? 'rgba(242,140,40,.3)' : 'rgba(148,163,184,.25)'}`,
      letterSpacing: '.03em', textTransform: 'uppercase',
    }}>
      {isLead ? '★ Lead' : 'Member'}
    </span>
  )
}

function formatDate(raw) {
  if (!raw) return '—'
  const d = new Date(raw)
  if (isNaN(d)) return '—'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function SkeletonBlock({ width = '100%', height = 16, style = {} }) {
  return (
    <div style={{
      width, height, borderRadius: 6,
      background: 'linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%)',
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite',
      ...style,
    }} />
  )
}

/* ── Toast ──────────────────────────────────────────────── */
function Toast({ message, type = 'success', onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3000)
    return () => clearTimeout(t)
  }, [onClose])

  return (
    <div style={{
      position: 'fixed', bottom: 28, right: 28, zIndex: 1100,
      padding: '12px 20px', borderRadius: 10,
      background: type === 'success' ? '#059669' : '#dc2626',
      color: '#fff', fontSize: 13, fontWeight: 600,
      boxShadow: '0 4px 20px rgba(0,0,0,.15)',
      fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
      display: 'flex', alignItems: 'center', gap: 8,
    }}>
      {type === 'success' ? '✓' : '✕'} {message}
    </div>
  )
}

export default function TeamDetailsModal({ teamId, onClose, onUpdated }) {
  // ── View state ─────────────────────────────────────────
  const [teamData, setTeamData] = useState(null)
  const [members, setMembers] = useState([])
  const [opportunities, setOpportunities] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // ── Edit state ─────────────────────────────────────────
  const [isEditMode, setIsEditMode] = useState(false)
  const [allUsers, setAllUsers] = useState([])
  const [loadingUsers, setLoadingUsers] = useState(false)
  const [editMembers, setEditMembers] = useState(new Set())
  const [editLeads, setEditLeads] = useState(new Set())
  const [userSearch, setUserSearch] = useState('')
  const [updating, setUpdating] = useState(false)

  // ── Toast ──────────────────────────────────────────────
  const [toast, setToast] = useState(null)

  // ── Track if team was modified (refresh list only on close) ──
  const [dirty, setDirty] = useState(false)

  // ── Fetch team details + users in parallel ─────────────
  const fetchDetails = useCallback((alsoFetchUsers = false) => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const promises = [getTeam(teamId)]
    if (alsoFetchUsers) {
      setLoadingUsers(true)
      promises.push(listTeamUsers().catch(() => []))
    }

    Promise.all(promises)
      .then(([teamData, usersData]) => {
        if (cancelled) return
        const team = teamData.team ?? teamData
        setTeamData(team)
        setMembers(teamData.members ?? team.members ?? [])
        setOpportunities(teamData.opportunities ?? team.opportunities ?? [])
        if (usersData !== undefined) {
          setAllUsers(usersData.users ?? usersData ?? [])
          setLoadingUsers(false)
        }
      })
      .catch(e => { if (!cancelled) setError(e?.message || 'Failed to load team.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [teamId])

  // Initial load: fetch team + users together
  useEffect(() => fetchDetails(true), [fetchDetails])

  // ── Close helper (refreshes list only if something changed) ──
  const handleClose = useCallback(() => {
    if (dirty) onUpdated?.()
    onClose?.()
  }, [dirty, onUpdated, onClose])

  // ── Close on Escape ────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !updating) handleClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handleClose, updating])

  // ── Enter edit mode (users already pre-loaded) ─────────
  const enterEditMode = useCallback(() => {
    setIsEditMode(true)
    setUserSearch('')
    const memberSet = new Set(members.map(m => m.user_id ?? m.id))
    const leadSet = new Set(members.filter(m => m.is_lead).map(m => m.user_id ?? m.id))
    setEditMembers(memberSet)
    setEditLeads(leadSet)
  }, [members])

  const cancelEdit = () => {
    setIsEditMode(false)
    setUserSearch('')
  }

  // ── Toggle member / lead ───────────────────────────────
  const toggleEditMember = useCallback((uid) => {
    setEditMembers(prev => {
      const next = new Set(prev)
      if (next.has(uid)) {
        next.delete(uid)
        setEditLeads(l => { const nl = new Set(l); nl.delete(uid); return nl })
      } else {
        next.add(uid)
      }
      return next
    })
  }, [])

  const toggleEditLead = useCallback((uid) => {
    setEditLeads(prev => {
      const next = new Set(prev)
      if (next.has(uid)) { next.delete(uid) }
      else { if (next.size >= 1) return prev; next.add(uid) }
      return next
    })
  }, [])

  // ── Update team ────────────────────────────────────────
  const handleUpdate = async () => {
    if (editMembers.size === 0) {
      setToast({ message: 'At least one member is required.', type: 'error' })
      return
    }
    setUpdating(true)
    try {
      const memberPayload = [...editMembers].map(uid => ({
        user_id: uid,
        is_lead: editLeads.has(uid),
      }))
      const res = await updateTeam(teamId, { members: memberPayload })
      // Use response data if available, else quick refetch
      if (res?.members || res?.team?.members) {
        const team = res.team ?? res
        setTeamData(prev => ({ ...prev, ...team }))
        setMembers(res.members ?? team.members ?? memberPayload)
      } else {
        fetchDetails(false)
      }
      setIsEditMode(false)
      setDirty(true)
      setToast({ message: 'Team updated successfully.', type: 'success' })
    } catch (e) {
      setToast({ message: e?.message || 'Failed to update team.', type: 'error' })
    } finally {
      setUpdating(false)
    }
  }

  // ── Filtered users in edit mode ────────────────────────
  const filteredUsers = allUsers.filter(u => {
    const q = userSearch.toLowerCase()
    const name = String(u.name || u.display_name || u.email || '').toLowerCase()
    const email = String(u.email || '').toLowerCase()
    return name.includes(q) || email.includes(q)
  })

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget && !updating) handleClose()
  }

  const teamName = teamData?.name || 'Team'
  const createdAt = formatDate(teamData?.created_at)

  /* ── Render ────────────────────────────────────────────── */
  return (
    <>
      <div
        onClick={handleOverlayClick}
        style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(15,23,42,.45)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: 24,
          fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
        }}
      >
        <div style={{
          width: '100%', maxWidth: 880, maxHeight: 'calc(100vh - 48px)',
          background: '#fff', borderRadius: 14,
          boxShadow: '0 20px 50px rgba(0,0,0,.25)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          {loading ? (
            <div style={{ padding: 28 }}>
              <SkeletonBlock width={260} height={22} style={{ marginBottom: 8 }} />
              <SkeletonBlock width={180} height={12} style={{ marginBottom: 24 }} />
              <div style={{ display: 'flex', gap: 16 }}>
                <SkeletonBlock height={220} style={{ flex: 1, borderRadius: 12 }} />
                <SkeletonBlock height={220} style={{ flex: 1, borderRadius: 12 }} />
              </div>
            </div>
          ) : error ? (
            <div style={{ padding: 28 }}>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                <button onClick={handleClose} style={closeBtnStyle} aria-label="Close">✕</button>
              </div>
              <div style={{ textAlign: 'center', padding: 32, color: '#dc2626', fontSize: 13, fontWeight: 600 }}>
                {error}
                <div style={{ marginTop: 12 }}>
                  <button onClick={fetchDetails} style={{
                    padding: '8px 18px', borderRadius: 8, border: 'none', background: PRIMARY,
                    color: '#fff', fontWeight: 600, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
                  }}>Retry</button>
                </div>
              </div>
            </div>
          ) : (
            <>
              {/* Header */}
              <div style={{
                padding: '20px 24px', borderBottom: '1px solid #edf2f7',
                display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                gap: 12, flexShrink: 0,
              }}>
                <div style={{ minWidth: 0 }}>
                  <h2 style={{
                    margin: 0, fontSize: 20, fontWeight: 800, color: PRIMARY,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {teamName}
                  </h2>
                  <p style={{ margin: '4px 0 0', fontSize: 12, color: '#94a3b8', fontWeight: 500 }}>
                    Created {createdAt} · {members.length} member{members.length !== 1 ? 's' : ''} · {opportunities.length} opportunit{opportunities.length !== 1 ? 'ies' : 'y'}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                  {!isEditMode ? (
                    <>
                      <button onClick={enterEditMode} style={{
                        padding: '8px 16px', borderRadius: 8,
                        border: `1.5px solid ${PRIMARY}`, background: 'transparent',
                        color: PRIMARY, fontWeight: 700, fontSize: 12,
                        cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
                      }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(11,60,93,.04)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                      >
                        Edit Members
                      </button>
                      <button onClick={handleClose} style={closeBtnStyle} aria-label="Close">✕</button>
                    </>
                  ) : (
                    <>
                      <button onClick={cancelEdit} disabled={updating} style={{
                        padding: '8px 16px', borderRadius: 8,
                        border: '1px solid #e2e8f0', background: '#f8fafc',
                        color: '#64748b', fontWeight: 600, fontSize: 12,
                        cursor: 'pointer', fontFamily: 'inherit',
                      }}>
                        Cancel
                      </button>
                      <button onClick={handleUpdate} disabled={updating || editMembers.size === 0} style={{
                        padding: '8px 18px', borderRadius: 8, border: 'none',
                        background: (updating || editMembers.size === 0) ? '#94a3b8' : PRIMARY,
                        color: '#fff', fontWeight: 700, fontSize: 12,
                        cursor: (updating || editMembers.size === 0) ? 'not-allowed' : 'pointer',
                        opacity: updating ? 0.7 : 1,
                        fontFamily: 'inherit',
                        boxShadow: editMembers.size > 0 ? '0 2px 8px rgba(11,60,93,.2)' : 'none',
                      }}>
                        {updating ? 'Updating…' : 'Update Team'}
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Two-column layout */}
              <div style={{
                padding: 20, display: 'flex', gap: 16, alignItems: 'stretch',
                overflowY: 'auto', flex: 1, minHeight: 0,
              }}>

                {/* ── LEFT: Members ──────────────────────────── */}
                <div style={{
                  flex: 1, minWidth: 0, borderRadius: 12,
                  border: '1px solid rgba(11,60,93,.08)', background: '#fff',
                  boxShadow: '0 1px 3px rgba(15,23,42,.04)',
                  display: 'flex', flexDirection: 'column', overflow: 'hidden',
                }}>
                  <div style={{
                    padding: '12px 16px', borderBottom: '1px solid #edf2f7',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    flexShrink: 0,
                  }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: PRIMARY }}>
                      Members
                    </span>
                    <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>
                      {isEditMode ? `${editMembers.size} selected · ${editLeads.size}/1 lead` : `${members.length} total`}
                    </span>
                  </div>

                  {isEditMode ? (
                    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                      <div style={{ padding: '10px 14px 0' }}>
                        <input
                          value={userSearch}
                          onChange={e => setUserSearch(e.target.value)}
                          placeholder="Search users…"
                          style={{
                            width: '100%', boxSizing: 'border-box',
                            padding: '8px 12px', borderRadius: 8, fontSize: 12,
                            border: '1px solid #e2e8f0', outline: 'none',
                            fontFamily: 'inherit', color: '#1e293b',
                          }}
                        />
                      </div>
                      {loadingUsers ? (
                        <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                          Loading users…
                        </div>
                      ) : (
                        <div style={{ maxHeight: 360, overflowY: 'auto', marginTop: 8 }}>
                          {filteredUsers.map(u => {
                            const uid = u.id ?? u.user_id ?? u.uid
                            const name = u.name || u.display_name || u.email || 'Unknown'
                            const isSelected = editMembers.has(uid)
                            const isLead = editLeads.has(uid)
                            return (
                              <div
                                key={uid}
                                style={{
                                  display: 'flex', alignItems: 'center', gap: 10,
                                  padding: '10px 14px',
                                  borderBottom: '1px solid #f1f5f9',
                                  background: isSelected ? 'rgba(11,60,93,.03)' : 'transparent',
                                  cursor: 'pointer', transition: 'background .1s',
                                }}
                                onClick={() => toggleEditMember(uid)}
                              >
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  readOnly
                                  style={{ accentColor: PRIMARY, cursor: 'pointer', flexShrink: 0 }}
                                />
                                <Avatar name={name} size={28} />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {name}
                                  </div>
                                  {u.email && (
                                    <div style={{ fontSize: 10, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {u.email}
                                    </div>
                                  )}
                                </div>
                                {isSelected && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); toggleEditLead(uid) }}
                                    style={{
                                      padding: '2px 9px', borderRadius: 10, fontSize: 9, fontWeight: 700,
                                      cursor: 'pointer', transition: 'all .15s', flexShrink: 0,
                                      border: isLead ? `1.5px solid ${ACCENT}` : '1.5px solid #cbd5e1',
                                      background: isLead ? 'rgba(242,140,40,.1)' : 'transparent',
                                      color: isLead ? ACCENT : '#94a3b8',
                                      letterSpacing: '.02em',
                                    }}
                                    title={editLeads.size >= 1 && !isLead ? 'Max 1 lead' : ''}
                                  >
                                    {isLead ? '★ Lead' : 'Set Lead'}
                                  </button>
                                )}
                              </div>
                            )
                          })}
                          {filteredUsers.length === 0 && (
                            <div style={{ textAlign: 'center', padding: 24, color: '#94a3b8', fontSize: 12 }}>
                              No users found
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ overflowY: 'auto' }}>
                      {members.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: 28, color: '#94a3b8', fontSize: 12 }}>
                          No members
                        </div>
                      ) : (
                        members.map((m, i) => {
                          const uid = m.user_id ?? m.id
                          const name = m.name || m.display_name || m.email || 'Unknown'
                          return (
                            <div key={uid ?? i} style={{
                              display: 'flex', alignItems: 'center', gap: 10,
                              padding: '12px 16px',
                              borderBottom: i < members.length - 1 ? '1px solid #f1f5f9' : 'none',
                            }}>
                              <Avatar name={name} size={32} />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {name}
                                </div>
                                {m.email && (
                                  <div style={{ fontSize: 11, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {m.email}
                                  </div>
                                )}
                              </div>
                              <RoleBadge isLead={m.is_lead} />
                            </div>
                          )
                        })
                      )}
                    </div>
                  )}
                </div>

                {/* ── RIGHT: Opportunities (read-only) ───────── */}
                <div style={{
                  flex: 1, minWidth: 0, borderRadius: 12,
                  border: '1px solid rgba(11,60,93,.08)', background: '#fff',
                  boxShadow: '0 1px 3px rgba(15,23,42,.04)',
                  display: 'flex', flexDirection: 'column', overflow: 'hidden',
                }}>
                  <div style={{
                    padding: '12px 16px', borderBottom: '1px solid #edf2f7',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    flexShrink: 0,
                  }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: PRIMARY }}>
                      Opportunities Assigned
                    </span>
                    <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>
                      {opportunities.length} total
                    </span>
                  </div>

                  {opportunities.length === 0 ? (
                    <div style={{
                      textAlign: 'center', padding: '36px 20px', color: '#94a3b8', fontSize: 12,
                    }}>
                      No opportunities assigned yet
                    </div>
                  ) : (
                    <div style={{ overflowY: 'auto' }}>
                      {opportunities.map((o, i) => {
                        const oid = o.id ?? o.opportunity_id
                        return (
                          <div key={oid ?? i} style={{
                            padding: '12px 16px',
                            borderBottom: i < opportunities.length - 1 ? '1px solid #f1f5f9' : 'none',
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {o.name || o.opportunity_id || 'Unnamed'}
                              </div>
                            </div>
                            {o.status && (
                              <span style={{
                                fontSize: 10, fontWeight: 600, color: '#94a3b8',
                                textTransform: 'uppercase', letterSpacing: '.03em',
                                flexShrink: 0, marginLeft: 10,
                              }}>
                                {o.status}
                              </span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Shimmer keyframes (for skeleton) */}
        <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
      </div>

      {/* Toast — sits above overlay */}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </>
  )
}

const closeBtnStyle = {
  width: 32, height: 32, borderRadius: 8,
  border: '1px solid #e2e8f0', background: '#f8fafc',
  color: '#64748b', fontSize: 14, fontWeight: 700,
  cursor: 'pointer', fontFamily: 'inherit',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  flexShrink: 0,
}
