import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { clearOpportunityIdsCache, fetchOpportunityIds } from '../services/opportunityIdsApi'
import { createOpportunity } from '../services/opportunitiesApi'
// ── Fiscal Quarter data ──────────────────────────────────────────────────────
const FISCAL_YEARS = [2025, 2026]
const QUARTERS = FISCAL_YEARS.flatMap(yr =>
  [1, 2, 3, 4].map(q => ({
    id: `Q${q} FY${yr}`,
    label: `Q${q} FY${yr}`,
    short: `Q${q}`,
    year: yr,
    q,
    // Jan–Mar = Q1, Apr–Jun = Q2, Jul–Sep = Q3, Oct–Dec = Q4
    startMonth: (q - 1) * 3 + 1,
  }))
)
const TODAY = new Date('2026-03-20')
const CURRENT_Q = QUARTERS.find(q => {
  const start = new Date(q.year, q.startMonth - 1, 1)
  const end   = new Date(q.year, q.startMonth + 2, 0)
  return TODAY >= start && TODAY <= end
}) || QUARTERS[4] // Q1 FY2026
const KNOWLEDGE_ASSIST_PAGE_SESSION_KEY = 'knowledgeAssist:lastPage'
const KNOWLEDGE_ASSIST_FRESH_LOGIN_RESET_KEY = 'knowledgeAssist:freshLoginReset'

function getStoredKnowledgeAssistPage() {
  try {
    const raw = sessionStorage.getItem(KNOWLEDGE_ASSIST_PAGE_SESSION_KEY)
    const parsed = Number(raw)
    if (Number.isInteger(parsed) && parsed > 0) return parsed
    return null
  } catch {
    return null
  }
}

function persistKnowledgeAssistPage(page) {
  const parsed = Number(page)
  if (!Number.isInteger(parsed) || parsed <= 0) return
  try {
    sessionStorage.setItem(KNOWLEDGE_ASSIST_PAGE_SESSION_KEY, String(parsed))
  } catch {
    /* noop */
  }
}

function consumeKnowledgeAssistFreshLoginReset() {
  try {
    const shouldReset = sessionStorage.getItem(KNOWLEDGE_ASSIST_FRESH_LOGIN_RESET_KEY) === '1'
    if (shouldReset) sessionStorage.removeItem(KNOWLEDGE_ASSIST_FRESH_LOGIN_RESET_KEY)
    return shouldReset
  } catch {
    return false
  }
}

function getKnowledgeAssistPageFromSearch(search) {
  try {
    const params = new URLSearchParams(String(search ?? ''))
    const parsed = Number(params.get('page'))
    if (Number.isInteger(parsed) && parsed > 0) return parsed
    return null
  } catch {
    return null
  }
}

function quarterStatus(q) {
  const end = new Date(q.year, q.startMonth + 2, 0)
  if (q.id === CURRENT_Q.id) return 'current'
  return end < TODAY ? 'past' : 'future'
}

// ── Fiscal Quarter Selector ──────────────────────────────────────────────────
function FiscalSelector({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const status = quarterStatus(value)

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      {/* Trigger */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 7,
          padding: '5px 12px 5px 10px', borderRadius: 20, cursor: 'pointer',
          background: open ? `rgba(var(--tint),.16)` : `rgba(var(--tint),.09)`,
          border: `1px solid ${open ? `rgba(var(--tint),.35)` : `rgba(var(--tint),.2)`}`,
          color: 'var(--p2)', fontFamily: 'var(--font)', transition: 'all .15s',
          boxShadow: open ? `0 0 0 3px rgba(var(--tint),.1)` : 'none',
        }}
      >
        {/* calendar icon */}
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.5px', textTransform: 'uppercase' }}>{value.label}</span>
        {status === 'current' && (
          <span style={{ fontSize: 8, fontWeight: 800, background: 'rgba(86,211,100,.15)', color: '#56D364', border: '1px solid rgba(86,211,100,.3)', borderRadius: 8, padding: '1px 5px', letterSpacing: '.3px' }}>LIVE</span>
        )}
        {/* chevron */}
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" style={{ transition: 'transform .2s', transform: open ? 'rotate(180deg)' : 'none', opacity: .6 }}>
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>

      {/* Dropdown panel */}
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 200,
          background: 'var(--bg2)', border: '1px solid var(--border)',
          borderRadius: 12, padding: '6px', minWidth: 210,
          boxShadow: '0 8px 24px rgba(15,23,42,.10)', animation: 'fadeIn .12s ease',
        }}>
          {/* Year groups */}
          {FISCAL_YEARS.map(yr => (
            <div key={yr}>
              <div style={{ fontSize: 8, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.8px', padding: '6px 10px 4px' }}>{yr}</div>
              {QUARTERS.filter(q => q.year === yr).map(q => {
                const st  = quarterStatus(q)
                const sel = q.id === value.id
                return (
                  <button
                    key={q.id}
                    onClick={() => { onChange(q); setOpen(false) }}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                      padding: '7px 10px', borderRadius: 8, border: 'none', cursor: 'pointer',
                      fontFamily: 'var(--font)', textAlign: 'left', transition: 'all .12s',
                      background: sel ? 'rgba(37,99,235,.12)' : 'transparent',
                    }}
                    onMouseEnter={e => { if (!sel) e.currentTarget.style.background = 'rgba(37,99,235,.05)' }}
                    onMouseLeave={e => { if (!sel) e.currentTarget.style.background = 'transparent' }}
                  >
                    {/* quarter pill */}
                    <span style={{
                      width: 28, fontSize: 9, fontWeight: 800, textAlign: 'center',
                      padding: '2px 0', borderRadius: 5,
                      background: sel ? 'rgba(37,99,235,.18)' : st === 'current' ? 'rgba(22,163,74,.12)' : 'var(--bg3)',
                      color: sel ? 'var(--p2)' : st === 'current' ? '#56D364' : st === 'past' ? 'var(--text3)' : 'var(--text2)',
                      border: sel ? '1px solid rgba(37,99,235,.3)' : st === 'current' ? '1px solid rgba(22,163,74,.25)' : '1px solid transparent',
                    }}>{q.short}</span>

                    <span style={{ flex: 1, fontSize: 12, fontWeight: sel ? 700 : 500, color: sel ? 'var(--text0)' : st === 'past' ? 'var(--text3)' : 'var(--text1)' }}>
                      FY{yr} · {['Jan–Mar','Apr–Jun','Jul–Sep','Oct–Dec'][q.q - 1]}
                    </span>

                    {st === 'current' && !sel && (
                      <span style={{ fontSize: 8, fontWeight: 700, color: '#56D364', background: 'rgba(86,211,100,.1)', border: '1px solid rgba(86,211,100,.2)', borderRadius: 6, padding: '1px 5px' }}>Current</span>
                    )}
                    {st === 'past' && (
                      <span style={{ fontSize: 8, color: 'var(--text3)' }}>Past</span>
                    )}
                    {sel && (
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--p2)" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                    )}
                  </button>
                )
              })}
            </div>
          ))}

          {/* footer hint */}
          <div style={{ borderTop: '1px solid var(--border)', marginTop: 4, padding: '7px 10px 2px', fontSize: 9, color: 'var(--text3)' }}>
            Fiscal year: Jan · Apr · Jul · Oct
          </div>
        </div>
      )}
    </div>
  )
}

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'

function IconFolderStar() {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      <path d="M12 9.5l1.2 2.4 2.7.4-2 1.9.5 2.7L12 15.9l-2.4 1.3.5-2.7-2-1.9 2.7-.4z" fill="currentColor" stroke="none" opacity={0.35} />
    </svg>
  )
}

function IconReview({ stroke = 'currentColor' }) {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M7 3h7l4 4v11a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z" />
      <path d="M14 3v4h4" />
      <circle cx="10.5" cy="13.5" r="2.25" />
      <path d="M12.2 15.2l2.1 2.1" />
    </svg>
  )
}

/** Completed / done — rounded square + check (distinct from circular “Ready” badge). */
function IconCompleted({ stroke = 'currentColor' }) {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="4" />
      <path d="M8 12.5l2.5 2.5 5-6" />
    </svg>
  )
}

/* ── Skeleton helpers ────────────────────────────────────────────────────── */
const SK_STYLE_TAG = `
  @keyframes skPulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: .45; }
  }
  .sk { border-radius: 5px; background: var(--bg4, #e2e8f0); animation: skPulse 1.5s ease-in-out infinite; }
`

function SkeletonMetricCard({ flex = 1, minWidth = 160 }) {
  return (
    <div style={{
      flex, minWidth, borderRadius: 16, padding: '18px 20px',
      border: '1px solid var(--border)', background: 'var(--bg2)',
      display: 'flex', gap: 14,
    }}>
      <div className="sk" style={{ width: 22, height: 22, borderRadius: 7, flexShrink: 0, marginTop: 2 }} />
      <div style={{ flex: 1 }}>
        <div className="sk" style={{ height: 30, width: '45%', borderRadius: 6 }} />
        <div className="sk" style={{ height: 9, width: '68%', borderRadius: 4, marginTop: 10, animationDelay: '.15s' }} />
        <div className="sk" style={{ height: 14, width: '38%', borderRadius: 4, marginTop: 12, animationDelay: '.28s' }} />
      </div>
    </div>
  )
}

function SkeletonTableRow({ last }) {
  return (
    <tr>
      <td style={{ padding: '16px 18px', borderBottom: last ? 'none' : '1px solid var(--border)', verticalAlign: 'top', maxWidth: 320 }}>
        <div className="sk" style={{ height: 13, width: '60%', borderRadius: 5 }} />
        <div className="sk" style={{ height: 9, width: '38%', borderRadius: 4, marginTop: 8, animationDelay: '.12s' }} />
      </td>
      <td style={{ padding: '16px 18px', borderBottom: last ? 'none' : '1px solid var(--border)', verticalAlign: 'middle', minWidth: 220 }}>
        <div className="sk" style={{ height: 10, borderRadius: 6, animationDelay: '.08s' }} />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 7 }}>
          <div className="sk" style={{ height: 8, width: '25%', borderRadius: 3, animationDelay: '.2s' }} />
          <div className="sk" style={{ height: 8, width: '25%', borderRadius: 3, animationDelay: '.3s' }} />
        </div>
      </td>
    </tr>
  )
}

/** KPI card: active = dark blue; inactive = light surface. No drop shadow. */
function OverviewMetricCard({
  active,
  flex = 1,
  minWidth = 160,
  val,
  label,
  badge,
  badgeTone,
  icon,
  showArrow,
  onClick,
}) {
  const [hov, setHov] = useState(false)
  const navyGrad = `linear-gradient(135deg, ${SI_NAVY} 0%, var(--si-navy-mid, #263060) 100%)`
  const badgeBgInactive = badgeTone === 'orange'
    ? 'rgba(232,83,46,.12)'
    : badgeTone === 'navy'
      ? 'rgba(27,38,79,.10)'
      : 'rgba(27,38,79,.10)'
  const badgeBorderInactive = badgeTone === 'orange'
    ? 'rgba(232,83,46,.28)'
    : badgeTone === 'navy'
      ? 'rgba(27,38,79,.22)'
      : 'rgba(27,38,79,.22)'
  const badgeColorInactive = badgeTone === 'orange' ? SI_ORANGE : SI_NAVY

  const inactiveBadge = badge && (
    <span style={{
      display: 'inline-block', marginTop: 10, fontSize: 8, fontWeight: 800, letterSpacing: '.1em',
      padding: '4px 8px', borderRadius: 6, background: badgeBgInactive, border: `1px solid ${badgeBorderInactive}`, color: badgeColorInactive,
    }}>{badge}</span>
  )
  const activeBadge = badge && (
    <span style={{
      display: 'inline-block', marginTop: 10, fontSize: 8, fontWeight: 800, letterSpacing: '.1em',
      padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,.15)', border: '1px solid rgba(255,255,255,.28)', color: '#fff',
    }}>{badge}</span>
  )
  if (active) {
    return (
      <button
        type="button"
        onClick={onClick}
        onMouseEnter={() => setHov(true)}
        onMouseLeave={() => setHov(false)}
        style={{
          flex,
          minWidth,
          textAlign: 'left',
          cursor: 'pointer',
          border: 'none',
          borderRadius: 16,
          padding: '18px 20px',
          background: navyGrad,
          color: '#fff',
          boxShadow: 'none',
          outline: hov ? `2px solid rgba(27,38,79,.35)` : 'none',
          outlineOffset: 2,
          transition: 'outline .15s ease',
          fontFamily: 'var(--font)',
          display: 'flex',
          alignItems: 'flex-start',
          gap: 14,
          position: 'relative',
        }}
      >
        <div style={{ opacity: 0.95, marginTop: 2 }}>{icon}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: -1.5, lineHeight: 1 }}>{String(val).padStart(2, '0')}</div>
          <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.9, marginTop: 6 }}>{label}</div>
          {badge && (badge === 'PRIMARY METRIC' ? (
            <span style={{
              display: 'inline-block', marginTop: 10, fontSize: 8, fontWeight: 800, letterSpacing: '.12em',
              padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,.15)', border: '1px solid rgba(255,255,255,.25)', color: '#fff',
            }}>PRIMARY METRIC</span>
          ) : activeBadge)}
        </div>
        {showArrow && <span style={{ position: 'absolute', right: 16, top: '50%', transform: 'translateY(-50%)', opacity: 0.75, fontSize: 18 }}>→</span>}
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        flex,
        minWidth,
        textAlign: 'left',
        cursor: 'pointer',
        border: '1px solid var(--si-nav-border, var(--border))',
        borderRadius: 16,
        padding: '18px 18px',
        background: 'var(--bg2)',
        boxShadow: 'none',
        outline: hov ? `2px solid rgba(27,38,79,.2)` : 'none',
        outlineOffset: 2,
        transition: 'outline .15s ease',
        fontFamily: 'var(--font)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        position: 'relative',
      }}
    >
      <div style={{ marginTop: 2 }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: -1, color: 'var(--text0)', lineHeight: 1 }}>{String(val).padStart(2, '0')}</div>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginTop: 6 }}>{label}</div>
        {badge === 'PRIMARY METRIC' ? (
          <span style={{
            display: 'inline-block', marginTop: 10, fontSize: 8, fontWeight: 800, letterSpacing: '.12em',
            padding: '4px 8px', borderRadius: 6, background: 'rgba(27,38,79,.08)', border: '1px solid rgba(27,38,79,.2)', color: SI_NAVY,
          }}>PRIMARY METRIC</span>
        ) : inactiveBadge}
      </div>
      {showArrow && <span style={{ position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)', opacity: 0.35, fontSize: 16, color: 'var(--text2)' }}>→</span>}
    </button>
  )
}

/**
 * Fully submitted / done opportunity: use whichever signals exist on the row (safe for partial API data).
 */
function isOpportunityCompleted(o) {
  if (!o || typeof o !== 'object') return false
  const apiSt = String(o.apiStatus ?? '').toLowerCase()
  if (apiSt === 'submitted') return true
  const compRaw = o.completion != null ? o.completion : o.percentage
  const comp = Number(compRaw)
  if (Number.isFinite(comp) && comp >= 100) return true
  const tq = Number(o.total_questions) || 0
  if (tq > 0) {
    const hc = Number(o.human_count) || 0
    if (hc >= tq) return true
  }
  return false
}

function mapApiIdRowToOpportunity(r) {
  const apiId = String(r.opportunity_id || '').trim()
  const humanCount = r.human_count ?? 0
  const aiCount = r.ai_count ?? 0
  const totalQuestions = r.total_questions ?? 0
  const totalPercent = r.percentage ?? 0
  const humanPercent = r.human_percentage ?? 0
  const aiPercent = r.ai_percentage ?? 0
  console.log('[Dashboard Progress Split]', {
    id: r.opportunity_id,
    humanCount,
    aiCount,
    totalPercent,
    humanPercent,
    aiPercent,
  })
  const out = {
    id: apiId,
    name: (r.name && String(r.name).trim()) || apiId,
    human_count: Number(humanCount) || 0,
    ai_count: Number(aiCount) || 0,
    total_questions: Number(totalQuestions) || 0,
    percentage: Number(totalPercent) || 0,
    human_percentage: Number(humanPercent) || 0,
    ai_percentage: Number(aiPercent) || 0,
  }
  out.status = 'review'

  const st = String(r.status ?? '').toLowerCase()
  out.apiStatus = st
  if (st === 'review' || st === 'progress') out.status = st
  else if (st === 'ready') out.status = 'review'

  const compIn = r.completion
  if (compIn != null && compIn !== '') {
    const n = Number(compIn)
    if (Number.isFinite(n)) out.completion = n
  }

  const pl = r.project_line ?? r.projectLine
  if (pl != null && String(pl).trim() !== '') out.projectLine = String(pl).trim()

  const cm = r.conflict_message ?? r.conflictMessage
  if (cm != null && String(cm).trim() !== '') out.conflictMessage = String(cm).trim()

  if (isOpportunityCompleted(out)) out.status = 'completed'

  return out
}

export default function Landing({ onOpenOpp, onCreateNewOpp, refreshKey = 0, onOpportunitiesRefresh }) {
  const navigate = useNavigate()
  const location = useLocation()
  const restoreStateRef = useRef(null)
  if (restoreStateRef.current == null) {
    const shouldStartFromFirstPage = consumeKnowledgeAssistFreshLoginReset()
    const restoredPageFromSearch = getKnowledgeAssistPageFromSearch(location.search)
    const restoredPageFromNavigation = Number(location.state?.knowledgeAssistPage)
    const navigationPage = Number.isInteger(restoredPageFromNavigation) && restoredPageFromNavigation > 0
      ? restoredPageFromNavigation
      : null
    const sessionPage = getStoredKnowledgeAssistPage()
    const restoredPage = shouldStartFromFirstPage ? 1 : (navigationPage ?? restoredPageFromSearch ?? sessionPage)
    const shouldRestorePage = shouldStartFromFirstPage || (Number.isInteger(restoredPage) && restoredPage > 0)
    restoreStateRef.current = {
      restoredPage,
      shouldRestorePage,
      initialPage: shouldRestorePage ? restoredPage : 1,
    }
  }
  const { shouldRestorePage, initialPage } = restoreStateRef.current
  const shouldForceRefresh = location.state?.forceRefresh === true || shouldRestorePage
  const didApplyInitialRestoreRef = useRef(false)
  const prevFilterSearchRef = useRef(null)
  const PAGE_SIZE = 10
  const [filter, setFilter] = useState('all')
  const [opportunities, setOpportunities] = useState([])
  const [idsLoading, setIdsLoading] = useState(true)
  const [idsError, setIdsError] = useState(null)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState('')
  const [createNotice, setCreateNotice] = useState('')

  const loadDashboard = useCallback(async (forceRefresh = false, requestedPage = 1) => {
    const parsedRequestedPage = Number(requestedPage)
    const safeRequestedPage =
      Number.isInteger(parsedRequestedPage) && parsedRequestedPage > 0 ? parsedRequestedPage : 1
    try {
      setIdsLoading(true)
      setIdsError(null)
      if (forceRefresh) clearOpportunityIdsCache()
      const rows = await fetchOpportunityIds({ bypassCache: forceRefresh })
      const baseRows = rows.map(r => mapApiIdRowToOpportunity(r))
      console.log('[List Refreshed]', {
        refreshKey,
        opportunityCount: baseRows.length,
        page: safeRequestedPage,
      })
      console.log('[Dashboard Summary API]', baseRows.map(o => ({
        id: o.id,
        human: o.human_count,
        ai: o.ai_count,
        total: o.percentage,
      })))
      setOpportunities(baseRows)
      setIdsLoading(false)
    } catch (e) {
      setOpportunities([])
      setIdsError(e instanceof Error ? e.message : 'Failed to load opportunities')
      setIdsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDashboard(refreshKey > 0 || shouldForceRefresh, initialPage)
  }, [loadDashboard, refreshKey, shouldForceRefresh, initialPage])

  useEffect(() => {
    if (!createNotice) return
    const t = window.setTimeout(() => setCreateNotice(''), 2800)
    return () => window.clearTimeout(t)
  }, [createNotice])

  const [page, setPage] = useState(initialPage)
  const [oppSearch, setOppSearch] = useState('')

  const setAndPersistPage = useCallback((nextPageOrUpdater) => {
    setPage((prevPage) => {
      const rawNext = typeof nextPageOrUpdater === 'function'
        ? nextPageOrUpdater(prevPage)
        : nextPageOrUpdater
      const parsedNext = Number(rawNext)
      if (!Number.isInteger(parsedNext) || parsedNext <= 0) return prevPage
      persistKnowledgeAssistPage(parsedNext)
      return parsedNext
    })
  }, [])

  const completedCount = useMemo(
    () => opportunities.filter(o => isOpportunityCompleted(o)).length,
    [opportunities],
  )

  /** Still needs review: not completed (submitted / 100% / all human answers) — excludes mistaken `review` rows after submit. */
  const readyForReviewCount = useMemo(
    () => opportunities.filter(o => o.status === 'review' && !isOpportunityCompleted(o)).length,
    [opportunities],
  )

  const filtered = useMemo(() => {
    const byStatus = opportunities.filter(o => {
      if (filter === 'all') return true
      if (filter === 'review') return o.status === 'review' && !isOpportunityCompleted(o)
      if (filter === 'completed') return isOpportunityCompleted(o)
      return true
    })
    const q = String(oppSearch ?? '').trim().toLowerCase()
    if (!q) return byStatus
    return byStatus.filter((o) => {
      const id = String(o.id ?? '').toLowerCase()
      const name = String(o.name ?? '').toLowerCase()
      const pl = String(o.projectLine ?? '').toLowerCase()
      return id.includes(q) || name.includes(q) || pl.includes(q)
    })
  }, [filter, opportunities, oppSearch])

  // Reset to page 1 only after an actual filter/search change (not on mount/restore).
  useEffect(() => {
    const prev = prevFilterSearchRef.current
    prevFilterSearchRef.current = { filter, oppSearch }
    if (!prev) return
    if (prev.filter === filter && prev.oppSearch === oppSearch) return
    setAndPersistPage(1)
  }, [filter, oppSearch, setAndPersistPage])

  useEffect(() => {
    if (didApplyInitialRestoreRef.current) return
    didApplyInitialRestoreRef.current = true
    if (!shouldRestorePage) return
    if (page === initialPage) return
    setAndPersistPage(initialPage)
  }, [initialPage, page, setAndPersistPage, shouldRestorePage])

  useEffect(() => {
    persistKnowledgeAssistPage(page)
  }, [page])

  useEffect(() => {
    const parsedSearchPage = getKnowledgeAssistPageFromSearch(location.search)
    const shouldUpdateSearch = parsedSearchPage !== page
    const statePage = Number(location.state?.knowledgeAssistPage)
    const shouldUpdateState = !Number.isInteger(statePage) || statePage !== page
    if (!shouldUpdateSearch && !shouldUpdateState) return

    const params = new URLSearchParams(location.search)
    params.set('page', String(page))
    const nextSearch = `?${params.toString()}`
    const forceRefresh = location.state?.forceRefresh === true
    navigate(
      { pathname: location.pathname, search: nextSearch },
      {
        replace: true,
        state: forceRefresh ? { knowledgeAssistPage: page, forceRefresh: true } : { knowledgeAssistPage: page },
      },
    )
  }, [location.pathname, location.search, location.state, navigate, page])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageSlice  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const openCreateModal = () => {
    console.log('[Create Opportunity Clicked]')
    setCreateModalOpen(true)
    setCreateError('')
  }

  const closeCreateModal = () => {
    if (createBusy) return
    setCreateModalOpen(false)
    setCreateError('')
  }

  const submitCreateOpportunity = async () => {
    if (createBusy) return
    const name = String(createName ?? '').trim()
    if (!name) {
      setCreateError('Opportunity Name is required.')
      return
    }
    const payload = { name }
    console.log('[Create Opportunity Payload]', payload)
    setCreateBusy(true)
    setCreateError('')
    try {
      const res = await createOpportunity(payload)
      console.log('[Create Opportunity Success]', res.raw)
      setCreateModalOpen(false)
      setCreateName('')
      setCreateNotice('Opportunity created successfully')
      await loadDashboard(true)
      console.log('[Opportunity List Refreshed]')
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create opportunity')
    } finally {
      setCreateBusy(false)
    }
  }

  return (
    <div style={{ animation: 'fadeUp .22s ease' }}>
      <style>{SK_STYLE_TAG}</style>

      {/* Hero */}
      <div style={{ position: 'relative', padding: '32px 24px 0', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: -100, left: '50%', transform: 'translateX(-50%)', width: 900, height: 450, background: `radial-gradient(ellipse at 50% 0%,rgba(var(--tint),0.15) 0%,rgba(var(--tint3),0.10) 35%,rgba(var(--tint2),0.08) 58%,transparent 75%)`, pointerEvents: 'none' }} />
        <div style={{ position: 'relative', maxWidth: 1100, margin: '0 auto' }}>

          {/* Fiscal period row (hidden for now)
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <FiscalSelector value={quarter} onChange={setQuarter} />
            {!isCurrentQ && (
              <span style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#E3B341', display: 'inline-block' }} />
                Viewing historical data — {quarterStatus(quarter) === 'past' ? 'closed period' : 'upcoming period'}
                <button onClick={() => setQuarter(CURRENT_Q)} style={{ marginLeft: 4, fontSize: 10, color: 'var(--p2)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font)', textDecoration: 'underline', padding: 0 }}>Back to current</button>
              </span>
            )}
          </div>
          */}

          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
            <div style={{ flex: '1 1 280px', minWidth: 0 }}>
              <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-.8px', marginBottom: 10, lineHeight: 1.15, color: SI_NAVY }}>
                Sales Intelligence Overview
              </div>
              <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 0, maxWidth: 720, lineHeight: 1.55 }}>
                Aggregated insights and real-time tracking for Relanto Forge strategic accounts. Use the filters below to drill down into specific pipeline health metrics.
              </div>
              {createNotice ? (
                <div
                  role="status"
                  aria-live="polite"
                  style={{
                    marginTop: 12,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '8px 12px',
                    borderRadius: 10,
                    fontSize: 12,
                    fontWeight: 700,
                    color: '#166534',
                    background: '#ECFDF3',
                    border: '1px solid #BBF7D0',
                  }}
                >
                  <span aria-hidden>✓</span>
                  {createNotice}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              onClick={openCreateModal}
              style={{
                padding: '12px 20px',
                borderRadius: 12,
                border: 'none',
                background: SI_ORANGE,
                color: '#fff',
                fontSize: 13,
                fontWeight: 700,
                cursor: 'pointer',
                fontFamily: 'var(--font)',
                boxShadow: '0 4px 16px rgba(232,83,46,.3)',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              Create opportunity
            </button>
          </div>
          <div style={{ height: 26 }} aria-hidden />

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
            {idsLoading ? (
              <>
                <SkeletonMetricCard flex={1.15} minWidth={200} />
                <SkeletonMetricCard />
                <SkeletonMetricCard />
              </>
            ) : (
              <>
                <OverviewMetricCard
                  active={filter === 'all'}
                  flex={1.15}
                  minWidth={200}
                  val={opportunities.length}
                  label="Total Opportunities"
                  badge="PRIMARY METRIC"
                  icon={<div style={{ color: filter === 'all' ? '#fff' : SI_NAVY }}><IconFolderStar /></div>}
                  onClick={() => setFilter('all')}
                />
                <OverviewMetricCard
                  active={filter === 'review'}
                  val={readyForReviewCount}
                  label="Ready for Review"
                  badge="ACTION REQUIRED"
                  badgeTone="orange"
                  icon={<div style={{ color: filter === 'review' ? '#fff' : SI_ORANGE }}><IconReview /></div>}
                  onClick={() => setFilter('review')}
                />
                <OverviewMetricCard
                  active={filter === 'completed'}
                  val={completedCount}
                  label="Completed"
                  badge="DONE"
                  badgeTone="navy"
                  icon={<div style={{ color: filter === 'completed' ? '#fff' : SI_NAVY }}><IconCompleted /></div>}
                  onClick={() => setFilter('completed')}
                />
              </>
            )}
          </div>
        </div>
      </div>

      {/* Table */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px 48px' }}>
        {/* Toolbar */}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14, padding: '22px 0 14px' }}>
          <div style={{ flex: '1 1 280px', minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 800, color: SI_NAVY, letterSpacing: '-.02em' }}>Opportunity Tracker</div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4, maxWidth: 420 }}>
              Real-time coverage and AI-driven alignment scoring. Click a row to open the Q&amp;A review.
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 12, fontSize: 10, fontWeight: 700, letterSpacing: '.06em' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: SI_NAVY }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: SI_NAVY, display: 'inline-block' }} />
                AI COVERAGE
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: SI_ORANGE }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: SI_ORANGE, display: 'inline-block' }} />
                HUMAN INSIGHT
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', gap: 5 }}>
              {['all', 'review', 'completed'].map(f => {
                const tone = f === 'all'
                  ? { border: `rgba(27,38,79,.35)`, bg: 'rgba(27,38,79,.08)', text: SI_NAVY }
                  : f === 'review'
                    ? { border: 'rgba(232,83,46,.35)', bg: 'rgba(232,83,46,.08)', text: SI_ORANGE }
                    : { border: 'rgba(27,38,79,.32)', bg: 'rgba(27,38,79,.07)', text: SI_NAVY }
                return (
                  <button key={f} type="button" onClick={() => setFilter(f)} style={{
                    padding: '6px 14px', borderRadius: 20, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    border: filter === f ? `1px solid ${tone.border}` : '1px solid var(--border)',
                    background: filter === f ? tone.bg : 'transparent',
                    color: filter === f ? tone.text : 'var(--text2)',
                    transition: 'all .15s', fontFamily: 'var(--font)',
                  }}>
                    {f === 'all'
                      ? `All (${opportunities.length})`
                      : f === 'review'
                        ? `Ready (${readyForReviewCount})`
                        : `Completed (${completedCount})`}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* Search — filters the paginated table (name, ID, project line) */}
        <div style={{ padding: '0 0 14px' }}>
          <label htmlFor="opp-table-search" className="visually-hidden" style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0 }}>
            Search opportunities
          </label>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            maxWidth: 420,
            padding: '8px 12px',
            borderRadius: 12,
            border: '1px solid var(--border)',
            background: 'var(--bg2)',
            boxShadow: '0 1px 2px rgba(15,23,42,.04)',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.2-4.2" />
            </svg>
            <input
              id="opp-table-search"
              type="search"
              value={oppSearch}
              onChange={e => setOppSearch(e.target.value)}
              placeholder="Search by name, ID, or project…"
              autoComplete="off"
              spellCheck={false}
              style={{
                flex: 1,
                minWidth: 0,
                border: 'none',
                background: 'transparent',
                fontSize: 13,
                fontFamily: 'var(--font)',
                color: 'var(--text1)',
                outline: 'none',
              }}
            />
            {oppSearch.trim() !== '' && (
              <button
                type="button"
                onClick={() => setOppSearch('')}
                aria-label="Clear search"
                style={{
                  flexShrink: 0,
                  padding: '2px 6px',
                  border: 'none',
                  borderRadius: 6,
                  background: 'rgba(27,38,79,.08)',
                  color: 'var(--text2)',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: 'var(--font)',
                }}
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Table card */}
        <div style={{
          background: 'var(--card-glass, var(--bg2))',
          border: '1px solid var(--border)',
          borderRadius: 20,
          overflow: 'hidden',
          boxShadow: 'var(--card-shadow, 0 8px 24px rgba(15,23,42,.08))',
          position: 'relative',
        }}>
          <div style={{ position: 'absolute', inset: 0, borderRadius: 20, background: `linear-gradient(135deg,rgba(var(--tint),.04) 0%,rgba(var(--tint3),.02) 50%,transparent 70%)`, pointerEvents: 'none' }} />
          <table style={{ width: '100%', borderCollapse: 'collapse', position: 'relative', zIndex: 1 }}>
            <thead>
              <tr style={{ background: 'var(--bg3)', borderBottom: '1px solid var(--border)' }}>
                {['Opportunity detail', 'Intelligence coverage (AI vs Human)'].map(h => (
                  <th key={h} style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.1em', padding: '12px 18px', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {idsLoading ? (
                Array.from({ length: 6 }, (_, idx) => (
                  <SkeletonTableRow key={idx} last={idx === 5} />
                ))
              ) : idsError ? (
                <tr>
                  <td colSpan={2} style={{ padding: '22px 18px', textAlign: 'center' }}>
                    <div style={{ color: '#b91c1c', fontSize: 12, fontWeight: 600, marginBottom: 10 }}>
                      Failed to load dashboard: {idsError}
                    </div>
                    <button
                      type="button"
                      onClick={() => loadDashboard()}
                      style={{
                        border: '1px solid var(--border)',
                        background: 'var(--bg2)',
                        borderRadius: 8,
                        padding: '6px 12px',
                        cursor: 'pointer',
                        fontFamily: 'var(--font)',
                        fontSize: 12,
                        fontWeight: 700,
                        color: SI_NAVY,
                      }}
                    >
                      Retry
                    </button>
                  </td>
                </tr>
              ) : pageSlice.length === 0 ? (
                <tr>
                  <td colSpan={2} style={{ padding: '28px 18px', textAlign: 'center', color: 'var(--text3)', fontSize: 13 }}>
                    {String(oppSearch ?? '').trim()
                      ? 'No opportunities match your search.'
                      : 'No opportunities in this filter.'}
                  </td>
                </tr>
              ) : (
                pageSlice.map((o, i) => (
                  <TableRow
                    key={o.id}
                    o={o}
                    last={i === pageSlice.length - 1}
                    onOpen={() => onOpenOpp(o.id, o.name || o.id, page)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {!idsLoading && totalPages > 1 && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            flexWrap: 'wrap', gap: 10, padding: '16px 2px 0',
          }}>
            <span style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 500 }}>
              {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length} opportunities
            </span>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {/* Prev */}
              <button
                type="button"
                disabled={page === 1}
                onClick={() => setAndPersistPage(p => p - 1)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '6px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                  border: '1px solid var(--border)', background: 'var(--bg2)',
                  color: page === 1 ? 'var(--text3)' : 'var(--text1)',
                  cursor: page === 1 ? 'default' : 'pointer', fontFamily: 'var(--font)',
                  opacity: page === 1 ? 0.45 : 1, transition: 'all .12s',
                }}
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M15 18l-6-6 6-6"/></svg>
                Prev
              </button>

              {/* Page pills */}
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter(n => n === 1 || n === totalPages || Math.abs(n - page) <= 1)
                .reduce((acc, n, idx, arr) => {
                  if (idx > 0 && n - arr[idx - 1] > 1) acc.push('…')
                  acc.push(n)
                  return acc
                }, [])
                .map((n, idx) =>
                  n === '…' ? (
                    <span key={`dot-${idx}`} style={{ fontSize: 11, color: 'var(--text3)', padding: '0 2px' }}>…</span>
                  ) : (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setAndPersistPage(n)}
                      style={{
                        minWidth: 30, height: 30, borderRadius: 7, fontSize: 11, fontWeight: n === page ? 800 : 500,
                        border: n === page ? `1px solid rgba(27,38,79,.35)` : '1px solid var(--border)',
                        background: n === page ? 'rgba(27,38,79,.09)' : 'var(--bg2)',
                        color: n === page ? SI_NAVY : 'var(--text2)',
                        cursor: 'pointer', fontFamily: 'var(--font)', transition: 'all .12s',
                      }}
                    >{n}</button>
                  )
                )}

              {/* Next */}
              <button
                type="button"
                disabled={page === totalPages}
                onClick={() => setAndPersistPage(p => p + 1)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '6px 12px', borderRadius: 8, fontSize: 11, fontWeight: 600,
                  border: '1px solid var(--border)', background: 'var(--bg2)',
                  color: page === totalPages ? 'var(--text3)' : 'var(--text1)',
                  cursor: page === totalPages ? 'default' : 'pointer', fontFamily: 'var(--font)',
                  opacity: page === totalPages ? 0.45 : 1, transition: 'all .12s',
                }}
              >
                Next
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M9 18l6-6-6-6"/></svg>
              </button>
            </div>
          </div>
        )}
      </div>
      {createModalOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Create opportunity"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15,23,42,.45)',
            zIndex: 2000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
          }}
          onClick={closeCreateModal}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: 460,
              background: '#fff',
              borderRadius: 14,
              border: '1px solid var(--border)',
              boxShadow: '0 24px 48px rgba(15,23,42,.22)',
              padding: 20,
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 800, color: SI_NAVY, marginBottom: 14 }}>
              Create Opportunity
            </div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 700, color: SI_NAVY, marginBottom: 6 }}>
              Name
            </label>
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="Enter Opportunity Name"
              disabled={createBusy}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid var(--border)',
                marginBottom: 10,
                fontSize: 13,
                fontFamily: 'var(--font)',
              }}
            />
            {createError ? (
              <div style={{ fontSize: 12, fontWeight: 600, color: '#b91c1c', marginBottom: 10 }}>
                {createError}
              </div>
            ) : null}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
              <button
                type="button"
                onClick={closeCreateModal}
                disabled={createBusy}
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: '1px solid var(--border)',
                  background: '#fff',
                  color: 'var(--text1)',
                  fontSize: 12,
                  fontWeight: 700,
                  fontFamily: 'var(--font)',
                  cursor: createBusy ? 'not-allowed' : 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitCreateOpportunity}
                disabled={createBusy}
                style={{
                  padding: '8px 14px',
                  borderRadius: 8,
                  border: 'none',
                  background: SI_ORANGE,
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 700,
                  fontFamily: 'var(--font)',
                  cursor: createBusy ? 'not-allowed' : 'pointer',
                }}
              >
                {createBusy ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function TableRow({ o, last, onOpen }) {
  const [hov, setHov] = useState(false)
  const aiCount = Number(o.ai_count) || 0
  const humanCount = Number(o.human_count) || 0
  const totalQuestions = Number(o.total_questions) || 0
  const totalPercent = Math.max(0, Math.min(100, Number(o.percentage) || 0))
  const aiPercent = Math.max(0, Math.min(100, Number(o.ai_percentage) || 0))
  const humanPercent = Math.max(0, Math.min(100, Number(o.human_percentage) || 0))
  const aiBarW = Math.max(0, Math.min(totalPercent, aiPercent))
  const humanBarW = Math.max(0, Math.min(totalPercent - aiBarW, humanPercent))
  const project = o.projectLine || 'Strategic initiative'
  const formatPct = (n) => `${Number(n || 0).toFixed(2).replace(/\.?0+$/, '')}%`

  return (
    <tr
      onClick={onOpen}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{ cursor: 'pointer', transition: 'background .12s', background: hov ? 'rgba(27,38,79,.04)' : 'transparent' }}
    >
      <td style={{ padding: '16px 18px', borderBottom: last ? 'none' : '1px solid var(--border)', verticalAlign: 'top', maxWidth: 320 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: hov ? SI_NAVY : 'var(--text0)', letterSpacing: '-.02em' }}>
          {o.name}
          <span style={{ fontWeight: 600, color: 'var(--text2)' }}> – {project}</span>
        </div>
        {o.conflictMessage && (
          <div style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 8,
            background: 'rgba(248,113,113,.1)', border: '1px solid rgba(248,113,113,.25)',
            fontSize: 11, fontWeight: 600, color: '#B91C1C', display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span aria-hidden>⚠</span>
            {o.conflictMessage}
          </div>
        )}
      </td>
      <td style={{ padding: '16px 18px', borderBottom: last ? 'none' : '1px solid var(--border)', verticalAlign: 'middle', minWidth: 220 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 180px', minWidth: 160 }}>
            <div style={{ height: 10, borderRadius: 6, overflow: 'hidden', display: 'flex', background: 'var(--bg4)' }}>
              <div style={{ width: `${aiBarW}%`, background: SI_NAVY }} />
              <div style={{ width: `${humanBarW}%`, background: SI_ORANGE }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 8, fontWeight: 700, letterSpacing: '.02em' }}>
              <span style={{ color: SI_NAVY }}>AI: {aiCount} ({formatPct(aiPercent)})</span>
              <span style={{ color: SI_ORANGE }}>Human: {humanCount} ({formatPct(humanPercent)})</span>
            </div>
            <div style={{ marginTop: 6, fontSize: 9, fontWeight: 600, color: 'var(--text3)', letterSpacing: '.01em' }}>
              Total Questions: {totalQuestions}
            </div>
          </div>
          <div style={{ fontSize: 13, fontWeight: 800, color: SI_NAVY, letterSpacing: '-0.3px', whiteSpace: 'nowrap' }}>
            {formatPct(totalPercent)}<span style={{ fontSize: 8, fontWeight: 700, color: 'var(--text3)', marginLeft: 3, letterSpacing: '.04em' }}>TOTAL</span>
          </div>
        </div>
      </td>
    </tr>
  )
}
