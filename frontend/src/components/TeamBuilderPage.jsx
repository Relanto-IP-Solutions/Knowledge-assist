import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTeams } from '../services/teamsApi'
import AddTeamModal from './AddTeamModal'
import TeamDetailsModal from './TeamDetailsModal'

const PRIMARY = '#0B3C5D'
const ACCENT = '#E8532E'
const GRADIENT = '#E8532E'

function formatDate(raw) {
  if (!raw) return '—'
  const d = new Date(raw)
  if (isNaN(d)) return '—'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function TeamBuilderPage({ onBack }) {
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [selectedTeamId, setSelectedTeamId] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  const fetchTeams = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listTeams()
      .then(data => { if (!cancelled) setTeams(data) })
      .catch(e => { if (!cancelled) setError(e?.message || 'Failed to load teams.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => fetchTeams(), [fetchTeams])

  const handleCreated = () => {
    setShowModal(false)
    setCurrentPage(1)
    fetchTeams()
  }

  const totalPages = Math.ceil(teams.length / itemsPerPage)
  const startIndex = (currentPage - 1) * itemsPerPage
  const paginatedTeams = teams.slice(startIndex, startIndex + itemsPerPage)

  return (
    <div style={{
      padding: '32px 28px', maxWidth: 1000, margin: '0 auto',
      fontFamily: 'var(--font, "Plus Jakarta Sans", sans-serif)',
    }}>
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" style={{ marginBottom: 18 }}>
        <ol style={{
          display: 'flex', alignItems: 'center', gap: 6,
          listStyle: 'none', margin: 0, padding: 0,
          fontSize: 11, fontWeight: 600, flexWrap: 'wrap',
        }}>
          {[
            { label: 'Sales Intelligence', to: '/knowledge-assist' },
            { label: 'Admin Panel', to: '/admin/requests' },
            { label: 'Team Management', to: null },
          ].map((crumb, index, arr) => {
            const isLast = index === arr.length - 1
            return (
              <li key={crumb.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {crumb.to && !isLast ? (
                  <Link
                    to={crumb.to}
                    style={{ color: 'rgba(77,85,119,.65)', fontWeight: 500, textDecoration: 'none', transition: 'color .15s' }}
                    onMouseEnter={e => { e.currentTarget.style.color = PRIMARY }}
                    onMouseLeave={e => { e.currentTarget.style.color = 'rgba(77,85,119,.65)' }}
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span style={{ color: isLast ? PRIMARY : 'rgba(77,85,119,.65)', fontWeight: isLast ? 700 : 500 }}>
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
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 28, flexWrap: 'wrap', gap: 16,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: PRIMARY, letterSpacing: '-.02em' }}>
            Team Management
          </h1>
          <p style={{ margin: '6px 0 0', fontSize: 13, color: '#94a3b8', fontWeight: 500 }}>
            Create and manage your sales teams
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '10px 22px', borderRadius: 10, border: 'none',
            background: GRADIENT, color: '#fff',
            fontWeight: 700, fontSize: 13,
            cursor: 'pointer', fontFamily: 'inherit',
            boxShadow: '0 4px 16px rgba(232,83,46,.3)',
            transition: 'transform .15s, box-shadow .15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = '0 6px 20px rgba(232,83,46,.35)' }}
          onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(232,83,46,.3)' }}
        >
          <span style={{ fontSize: 16, lineHeight: 1, fontWeight: 400 }}>+</span>
          Add Team
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div style={{
          borderRadius: 14, overflow: 'hidden',
          boxShadow: '0 2px 12px rgba(15,23,42,.06), 0 0 0 1px rgba(11,60,93,.06)',
          background: '#fff',
        }}>
          <div style={{ height: 2, background: PRIMARY }} />
          <style>{`@keyframes shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}`}</style>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'inherit' }}>
            <thead>
              <tr style={{ background: 'rgba(11,60,93,.02)' }}>
                {['Team Name', 'Members', 'Opportunities Assigned', 'Created On', ''].map((label, i) => (
                  <th key={i} style={{
                    padding: '14px 20px', fontSize: 10, fontWeight: 700,
                    color: '#94a3b8', textAlign: i === 1 || i === 2 ? 'center' : 'left',
                    textTransform: 'uppercase', letterSpacing: '.08em',
                    borderBottom: '1px solid #edf2f7',
                    ...(i === 4 ? { width: 140 } : {}),
                  }}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...Array(5)].map((_, idx) => (
                <tr key={idx} style={{ borderBottom: idx < 4 ? '1px solid #f1f5f9' : 'none' }}>
                  {[160, 60, 100, 90, 80].map((w, ci) => (
                    <td key={ci} style={{ padding: '16px 20px', textAlign: ci === 1 || ci === 2 ? 'center' : 'left' }}>
                      <div style={{
                        height: 14, borderRadius: 6, width: w,
                        background: 'linear-gradient(90deg, #edf2f7 25%, #f8fafc 50%, #edf2f7 75%)',
                        backgroundSize: '800px 100%',
                        animation: 'shimmer 1.5s infinite linear',
                        ...(ci === 1 || ci === 2 ? { margin: '0 auto' } : {}),
                      }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : error ? (
        <div style={{
          textAlign: 'center', padding: 48, color: '#dc2626',
          fontSize: 13, fontWeight: 600,
        }}>
          {error}
          <div style={{ marginTop: 12 }}>
            <button
              onClick={fetchTeams}
              style={{
                padding: '8px 18px', borderRadius: 8, border: 'none',
                background: PRIMARY, color: '#fff', fontWeight: 600,
                fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Retry
            </button>
          </div>
        </div>
      ) : teams.length === 0 ? (
        /* Empty state */
        <div style={{
          textAlign: 'center', padding: '56px 24px',
          borderRadius: 16, background: '#fafbfc',
          border: '2px dashed rgba(232,83,46,.25)',
        }}>
          <div style={{ fontSize: 44, marginBottom: 14 }}>👥</div>
          <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: PRIMARY }}>
            No teams created yet
          </p>
          <p style={{ margin: '8px 0 22px', fontSize: 13, color: '#94a3b8' }}>
            Get started by creating your first team.
          </p>
          <button
            onClick={() => setShowModal(true)}
            style={{
              padding: '10px 22px', borderRadius: 10, border: 'none',
              background: GRADIENT, color: '#fff',
              fontWeight: 700, fontSize: 13, cursor: 'pointer',
              fontFamily: 'inherit',
              boxShadow: '0 4px 16px rgba(232,83,46,.3)',
            }}
          >
            Create your first team
          </button>
        </div>
      ) : (
        /* Team table with gradient orange top border */
        <div style={{
          borderRadius: 14, overflow: 'hidden',
          boxShadow: '0 2px 12px rgba(15,23,42,.06), 0 0 0 1px rgba(11,60,93,.06)',
          background: '#fff',
        }}>
          {/* Top accent bar */}
          <div style={{
            height: 2,
            background: PRIMARY,
          }} />
          <table style={{
            width: '100%', borderCollapse: 'collapse',
            fontFamily: 'inherit',
          }}>
            <thead>
              <tr style={{ background: 'rgba(11,60,93,.02)' }}>
                {[
                  { label: 'Team Name', align: 'left' },
                  { label: 'Members', align: 'center' },
                  { label: 'Opportunities Assigned', align: 'center' },
                  { label: 'Created On', align: 'left' },
                  { label: '', align: 'right', width: 140 },
                ].map((col, i) => (
                  <th key={i} style={{
                    padding: '14px 20px', fontSize: 10, fontWeight: 700,
                    color: '#94a3b8', textAlign: col.align,
                    textTransform: 'uppercase', letterSpacing: '.08em',
                    borderBottom: '1px solid #edf2f7',
                    ...(col.width ? { width: col.width } : {}),
                  }}>
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paginatedTeams.map((team, idx) => {
                const id = team.id ?? team.team_id
                return (
                  <tr
                    key={id}
                    style={{
                      cursor: 'pointer',
                      transition: 'background .15s',
                      borderBottom: idx < paginatedTeams.length - 1 ? '1px solid #f1f5f9' : 'none',
                    }}
                    onClick={() => setSelectedTeamId(id)}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(232,83,46,.03)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                  >
                    <td style={{ padding: '16px 20px' }}>
                      <span style={{ fontSize: 14, fontWeight: 700, color: PRIMARY, letterSpacing: '-.01em' }}>
                        {team.name}
                      </span>
                    </td>
                    <td style={{ padding: '16px 20px', textAlign: 'center', fontSize: 13, fontWeight: 700, color: PRIMARY }}>
                      {team.member_count ?? 0}
                    </td>
                    <td style={{ padding: '16px 20px', textAlign: 'center', fontSize: 13, fontWeight: 700, color: PRIMARY }}>
                      {team.opportunity_count ?? 0}
                    </td>
                    <td style={{ padding: '16px 20px', fontSize: 12, color: '#64748b', fontWeight: 500 }}>
                      {formatDate(team.created_at)}
                    </td>
                    <td style={{ padding: '16px 20px', textAlign: 'right' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setSelectedTeamId(id) }}
                        style={{
                          padding: '6px 16px', borderRadius: 8, fontSize: 12, fontWeight: 700,
                          border: `1.5px solid ${ACCENT}`, background: 'transparent',
                          color: ACCENT, cursor: 'pointer', fontFamily: 'inherit',
                          transition: 'all .2s', whiteSpace: 'nowrap',
                          letterSpacing: '.01em',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = ACCENT; e.currentTarget.style.color = '#fff'; e.currentTarget.style.boxShadow = '0 2px 8px rgba(232,83,46,.25)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = ACCENT; e.currentTarget.style.boxShadow = 'none' }}
                      >
                        Manage →
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          
          {/* Pagination */}
          <div style={{
            padding: '16px 20px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'rgba(11,60,93,.01)',
            borderTop: '1px solid #f1f5f9',
            fontSize: 13,
            color: '#64748b',
          }}>
            <span style={{ fontWeight: 500 }}>
              Showing {startIndex + 1}–{Math.min(startIndex + itemsPerPage, teams.length)} of {teams.length} teams
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                style={{
                  padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                  border: `1px solid ${currentPage === 1 ? '#e2e8f0' : '#cbd5e1'}`,
                  background: '#fff', color: currentPage === 1 ? '#cbd5e1' : PRIMARY,
                  cursor: currentPage === 1 ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
                  transition: 'all .2s',
                }}
                onMouseEnter={e => { if (currentPage > 1) { e.currentTarget.style.background = 'rgba(11,60,93,.05)'; e.currentTarget.style.borderColor = PRIMARY } }}
                onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.borderColor = currentPage === 1 ? '#e2e8f0' : '#cbd5e1' }}
              >
                ← Previous
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '0 8px' }}>
                {Array.from({ length: totalPages }, (_, i) => {
                  const pageNum = i + 1
                  const isActive = pageNum === currentPage
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setCurrentPage(pageNum)}
                      style={{
                        width: 32, height: 32, borderRadius: 6, fontSize: 12, fontWeight: 700,
                        border: isActive ? `2px solid ${PRIMARY}` : '1px solid #e2e8f0',
                        background: isActive ? PRIMARY : '#fff',
                        color: isActive ? '#fff' : PRIMARY,
                        cursor: 'pointer', fontFamily: 'inherit',
                        transition: 'all .2s',
                      }}
                      onMouseEnter={e => { if (!isActive) { e.currentTarget.style.borderColor = PRIMARY; e.currentTarget.style.color = PRIMARY } }}
                      onMouseLeave={e => { if (!isActive) { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.color = PRIMARY } }}
                    >
                      {pageNum}
                    </button>
                  )
                })}
              </div>
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                style={{
                  padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                  border: `1px solid ${currentPage === totalPages ? '#e2e8f0' : '#cbd5e1'}`,
                  background: '#fff', color: currentPage === totalPages ? '#cbd5e1' : PRIMARY,
                  cursor: currentPage === totalPages ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
                  transition: 'all .2s',
                }}
                onMouseEnter={e => { if (currentPage < totalPages) { e.currentTarget.style.background = 'rgba(11,60,93,.05)'; e.currentTarget.style.borderColor = PRIMARY } }}
                onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.borderColor = currentPage === totalPages ? '#e2e8f0' : '#cbd5e1' }}
              >
                Next →
              </button>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <AddTeamModal
          onClose={() => setShowModal(false)}
          onCreated={handleCreated}
        />
      )}

      {selectedTeamId && (
        <TeamDetailsModal
          teamId={selectedTeamId}
          onClose={() => setSelectedTeamId(null)}
          onUpdated={fetchTeams}
        />
      )}
    </div>
  )
}
