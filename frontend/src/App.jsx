import { useState, useEffect, useRef } from 'react'
import { Routes, Route, Navigate, useNavigate, useParams, useLocation } from 'react-router-dom'
import Topbar from './components/Topbar'
import Landing from './components/Landing'
import QAPage from './components/QAPage'
import SourcesPage from './components/SourcesPage'
import GmailResultPage from './components/GmailResultPage'
import CreateOpportunityPage from './components/CreateOpportunityPage'
import AdminRequestsPage from './components/AdminRequestsPage'
import TeamBuilderPage from './components/TeamBuilderPage'
import LoginWithTheme from './components/Login'
import { subscribeAuth, signOutUser, forceRegisterCurrentUser } from './services/authService'
import {
  OAUTH_RETURN_CREATE_OPP_KEY,
  OAUTH_OPP_ID_KEY,
  setCachedGmailConnectInfo,
  setCachedGmailMetrics,
} from './services/integrationsAuthApi'
import {
  GMAIL_CONNECTOR_EMAIL_SESSION_KEY,
  gmailConnectorEmailSessionKey,
  GMAIL_RESUME_POLL_OID_KEY,
} from './hooks/useGmailConnector'

export const MODULES = [
  { id: 'sales', label: 'Sales Intelligence', icon: null, enabled: true },
  { id: 'market', label: 'Market Intelligence', icon: null, enabled: true },
]

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

function setStoredKnowledgeAssistPage(page) {
  const parsed = Number(page)
  if (!Number.isInteger(parsed) || parsed <= 0) return
  try {
    sessionStorage.setItem(KNOWLEDGE_ASSIST_PAGE_SESSION_KEY, String(parsed))
  } catch {
    /* noop */
  }
}

function markKnowledgeAssistFreshLoginReset() {
  try {
    sessionStorage.setItem(KNOWLEDGE_ASSIST_FRESH_LOGIN_RESET_KEY, '1')
  } catch {
    /* noop */
  }
}

function clearPostLoginSessionCache() {
  try {
    sessionStorage.removeItem(OAUTH_RETURN_CREATE_OPP_KEY)
    sessionStorage.removeItem(OAUTH_OPP_ID_KEY)
    sessionStorage.removeItem(GMAIL_RESUME_POLL_OID_KEY)
    sessionStorage.removeItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY)
  } catch {
    /* noop */
  }
}

function parsePositivePage(value) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function getKnowledgeAssistPageFromSearch(search) {
  try {
    const params = new URLSearchParams(String(search ?? ''))
    return parsePositivePage(params.get('kaPage'))
  } catch {
    return null
  }
}

function SourcesRoute({ user }) {
  const { opportunityId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const isOpportunityLocked = location.state?.opportunityLocked === true
  const searchPage = getKnowledgeAssistPageFromSearch(location.search)
  const statePage = parsePositivePage(location.state?.knowledgeAssistPage)
  const storedPage = getStoredKnowledgeAssistPage()
  const knowledgeAssistPage = searchPage ?? statePage ?? storedPage
  const knowledgeAssistNavState = Number.isFinite(Number(knowledgeAssistPage))
    ? { knowledgeAssistPage: Number(knowledgeAssistPage), forceRefresh: true }
    : { forceRefresh: true }
  const safeKnowledgeAssistPage = Number(knowledgeAssistPage)
  const knowledgeAssistBackTarget =
    Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0
      ? { pathname: '/homepage', state: { knowledgeAssistPage: safeKnowledgeAssistPage, forceRefresh: true } }
      : { pathname: '/homepage' }

  useEffect(() => {
    if (!Number.isInteger(safeKnowledgeAssistPage) || safeKnowledgeAssistPage <= 0) return
    setStoredKnowledgeAssistPage(safeKnowledgeAssistPage)
  }, [safeKnowledgeAssistPage])

  // Popup lands here after per-opportunity Gmail connect OAuth.
  useEffect(() => {
    if (!window.opener) return
    const params = new URLSearchParams(window.location.search)
    if (params.get('gmail_connect') !== 'success') return
    try {
      window.opener.postMessage(
        { type: 'gmail_oauth_result', gmailConnect: 'success', oid: opportunityId },
        window.location.origin,
      )
    } catch {
      /* noop */
    }
    window.close()
  }, [opportunityId])

  return (
    <SourcesPage
      opportunityId={opportunityId}
      opportunityName={opportunityId}
      isOpportunityLocked={isOpportunityLocked}
      userEmail={user?.email || ''}
      onContinue={() => navigate(
        '/qa/' + opportunityId,
        {
          state: {
            ...(location.state ?? {}),
            ...(Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0
              ? { knowledgeAssistPage: safeKnowledgeAssistPage }
              : {}),
            opportunityLocked: isOpportunityLocked,
          },
        },
      )}
      onBack={() => {
        if (Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0) {
          setStoredKnowledgeAssistPage(safeKnowledgeAssistPage)
        }
        navigate(knowledgeAssistBackTarget, { state: knowledgeAssistNavState })
      }}
    />
  )
}

function LegacySourcesRedirect() {
  const { oid } = useParams()
  return <Navigate to={`/data-connectors/${oid}`} replace />
}

function QARoute({ onReviewSaved }) {
  const { opportunityId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const isOpportunityLocked = location.state?.opportunityLocked === true
  const searchPage = getKnowledgeAssistPageFromSearch(location.search)
  const statePage = parsePositivePage(location.state?.knowledgeAssistPage)
  const storedPage = getStoredKnowledgeAssistPage()
  const knowledgeAssistPage = searchPage ?? statePage ?? storedPage
  const knowledgeAssistNavState = Number.isFinite(Number(knowledgeAssistPage))
    ? { knowledgeAssistPage: Number(knowledgeAssistPage), forceRefresh: true }
    : { forceRefresh: true }
  const safeKnowledgeAssistPage = Number(knowledgeAssistPage)
  const knowledgeAssistBackTarget =
    Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0
      ? { pathname: '/homepage', state: { knowledgeAssistPage: safeKnowledgeAssistPage, forceRefresh: true } }
      : { pathname: '/homepage' }

  useEffect(() => {
    if (!Number.isInteger(safeKnowledgeAssistPage) || safeKnowledgeAssistPage <= 0) return
    setStoredKnowledgeAssistPage(safeKnowledgeAssistPage)
  }, [safeKnowledgeAssistPage])
  return (
    <QAPage
      oppId={opportunityId}
      isOpportunityLocked={isOpportunityLocked}
      onBack={() => {
        if (Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0) {
          setStoredKnowledgeAssistPage(safeKnowledgeAssistPage)
        }
        navigate(knowledgeAssistBackTarget, { state: knowledgeAssistNavState })
      }}
      onBackToDataConnectors={() => navigate(
        '/data-connectors/' + opportunityId,
        {
          state: {
            ...(location.state ?? {}),
            ...(Number.isInteger(safeKnowledgeAssistPage) && safeKnowledgeAssistPage > 0
              ? { knowledgeAssistPage: safeKnowledgeAssistPage }
              : {}),
            opportunityLocked: isOpportunityLocked,
          },
        },
      )}
      onReviewSaved={onReviewSaved}
    />
  )
}

function CreateRoute({ user, onBackToKnowledgeAssist, onCreated }) {
  return (
    <CreateOpportunityPage
      user={user}
      onBack={onBackToKnowledgeAssist}
      onCreated={onCreated}
    />
  )
}

function getRoles(user) {
  const roles = Array.isArray(user?.roles_assigned) ? user.roles_assigned : []
  return roles.map((role) => String(role || '').trim().toUpperCase()).filter(Boolean)
}

function isAdminUser(user) {
  return getRoles(user).includes('ADMIN')
}

function ProtectedRoute({ user, children }) {
  const location = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

function PublicOnlyRoute({ user, children }) {
  if (user) {
    return <Navigate to="/homepage" replace />
  }
  return children
}

function RoleGuard({ user, allow = [], children }) {
  const allowed = allow.map((role) => String(role || '').trim().toUpperCase()).filter(Boolean)
  const hasAccess = allowed.length === 0 || getRoles(user).some((role) => allowed.includes(role))
  if (!hasAccess) return <Navigate to="/homepage" replace />
  return children
}

export default function App() {
  const navigate = useNavigate()
  const hasHandledInitialAuthRef = useRef(false)
  const previousAuthUidRef = useRef(null)
  const registerPingedUidRef = useRef(null)
  const [user, setUser] = useState(null)
  const [authReady, setAuthReady] = useState(false)
  const [activeModule, setActiveModule] = useState('sales')
  const [landingRefreshKey, setLandingRefreshKey] = useState(0)
  const isAdmin = isAdminUser(user)
  const getKnowledgeAssistNavState = () => {
    const page = getStoredKnowledgeAssistPage()
    return Number.isInteger(page) && page > 0
      ? { knowledgeAssistPage: page, forceRefresh: true }
      : { forceRefresh: true }
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'relanto')
  }, [])

  useEffect(() => {
    return subscribeAuth((nextUser) => {
      const nextUid = nextUser?.uid ?? null
      const isFreshLogin = hasHandledInitialAuthRef.current && !previousAuthUidRef.current && !!nextUid
      if (isFreshLogin) {
        clearPostLoginSessionCache()
        setStoredKnowledgeAssistPage(1)
        markKnowledgeAssistFreshLoginReset()
        navigate(
          { pathname: '/homepage' },
          { replace: true, state: { knowledgeAssistPage: 1, forceRefresh: true } },
        )
      }
      previousAuthUidRef.current = nextUid
      hasHandledInitialAuthRef.current = true
      setUser(nextUser)
      setAuthReady(true)
    })
  }, [navigate])

  useEffect(() => {
    if (!authReady || !user?.uid) return
    if (registerPingedUidRef.current === user.uid) return
    registerPingedUidRef.current = user.uid
    forceRegisterCurrentUser().catch(() => {
      /* noop: auth subscriber already has fallback handling */
    })
  }, [authReady, user?.uid])

  const bumpDashboardRefresh = () => setLandingRefreshKey(k => k + 1)

  // Restore post-OAuth destination.
  useEffect(() => {
    if (!authReady || !user) return
    try {
      const returnDest = sessionStorage.getItem(OAUTH_RETURN_CREATE_OPP_KEY)
      if (returnDest === 'create-opp') {
        sessionStorage.removeItem(OAUTH_RETURN_CREATE_OPP_KEY)
        navigate('/create')
      } else if (returnDest === 'sources') {
        const oid = sessionStorage.getItem(OAUTH_OPP_ID_KEY)
        sessionStorage.removeItem(OAUTH_RETURN_CREATE_OPP_KEY)
        sessionStorage.removeItem(OAUTH_OPP_ID_KEY)
        if (oid) navigate('/data-connectors/' + oid)
        else navigate('/homepage', { state: getKnowledgeAssistNavState() })
      }
    } catch {
      /* noop */
    }
  }, [authReady, user, navigate])

  // Listen for postMessages from Gmail OAuth popups.
  useEffect(() => {
    const handler = (event) => {
      if (event.origin !== window.location.origin) return
      const msg = event.data
      if (!msg || msg.type !== 'gmail_oauth_result') return

      if (msg.gmailDiscover) {
        bumpDashboardRefresh()
        navigate('/homepage', { state: getKnowledgeAssistNavState() })
      }

      if (msg.gmailConnect && msg.oid) {
        const userEmail = (() => {
          try {
            const scoped = sessionStorage.getItem(gmailConnectorEmailSessionKey(msg.oid))
            if (scoped) return scoped
            return sessionStorage.getItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY) || undefined
          } catch {
            return undefined
          }
        })()

        setCachedGmailConnectInfo(msg.oid, {
          status: 'ACTIVE',
          requires_oauth: false,
          ...(msg.connectResult || {}),
        })
        if (msg.metrics && userEmail !== undefined) {
          setCachedGmailMetrics(msg.oid, userEmail, msg.metrics)
        }

        try {
          sessionStorage.removeItem(GMAIL_RESUME_POLL_OID_KEY)
        } catch {
          /* noop */
        }

        navigate('/data-connectors/' + msg.oid)
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [navigate])

  const handleLogin = (loggedInUser, module) => {
    setUser(loggedInUser)
    if (module) setActiveModule(module)
    // Fresh sign-in should always start the dashboard table at page 1.
    clearPostLoginSessionCache()
    setStoredKnowledgeAssistPage(1)
    markKnowledgeAssistFreshLoginReset()
    navigate(
      { pathname: '/homepage' },
      { replace: true, state: { knowledgeAssistPage: 1, forceRefresh: true } },
    )
  }

  const handleLogout = async () => {
    await signOutUser()
    setUser(null)
    // Reset landing pagination context on sign-out so next sign-in starts fresh.
    setStoredKnowledgeAssistPage(1)
    navigate(
      { pathname: '/homepage' },
      { replace: true, state: { knowledgeAssistPage: 1, forceRefresh: true } },
    )
  }

  const switchModule = (mod) => {
    if (!mod.enabled) return
    setActiveModule(mod.id)
    navigate('/homepage', { state: getKnowledgeAssistNavState() })
  }

  if (!authReady) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)',
          color: 'var(--text2)',
          fontFamily: "'Plus Jakarta Sans', sans-serif",
          fontSize: 14,
        }}
      >
        Loading...
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {user && (
        <Topbar
          activeModule={activeModule}
          onLogoClick={() => navigate('/homepage', { state: getKnowledgeAssistNavState() })}
          onSwitchModule={switchModule}
          user={user}
          isAdmin={isAdmin}
          onLogout={handleLogout}
          onNavigate={(path) => navigate(path)}
        />
      )}

      {activeModule === 'sales' && (
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnlyRoute user={user}>
                <LoginWithTheme onLogin={handleLogin} theme="relanto" />
              </PublicOnlyRoute>
            }
          />
          <Route
            path="/homepage"
            element={
              <ProtectedRoute user={user}>
                <Landing
                  key={landingRefreshKey}
                  user={user}
                  onOpenOpp={(id, _name, page, isOpportunityLocked = false) => {
                    const parsedPage = Number(page)
                    if (Number.isInteger(parsedPage) && parsedPage > 0) {
                      setStoredKnowledgeAssistPage(parsedPage)
                    }
                    navigate(
                      '/data-connectors/' + id,
                      {
                      state: {
                        ...(Number.isInteger(parsedPage) && parsedPage > 0
                          ? { knowledgeAssistPage: parsedPage }
                          : {}),
                        opportunityLocked: Boolean(isOpportunityLocked),
                      },
                      },
                    )
                  }}
                  userEmail={user?.email || ''}
                  refreshKey={landingRefreshKey}
                  onOpportunitiesRefresh={bumpDashboardRefresh}
                  onAdminPanel={isAdmin ? () => navigate('/admin/requests') : undefined}
                />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to={user ? '/homepage' : '/login'} replace />} />
          <Route
            path="/knowledge-assist"
            element={<Navigate to={user ? '/homepage' : '/login'} replace />}
          />
          <Route
            path="/data-connectors/:opportunityId"
            element={
              <ProtectedRoute user={user}>
                <SourcesRoute user={user} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/sources/:oid"
            element={
              <ProtectedRoute user={user}>
                <LegacySourcesRedirect />
              </ProtectedRoute>
            }
          />
          <Route
            path="/qa/:opportunityId"
            element={
              <ProtectedRoute user={user}>
                <QARoute onReviewSaved={bumpDashboardRefresh} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/create"
            element={
              <ProtectedRoute user={user}>
                <CreateRoute user={user} onBackToKnowledgeAssist={() => navigate('/homepage', { state: getKnowledgeAssistNavState() })} onCreated={bumpDashboardRefresh} />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/requests"
            element={
              <ProtectedRoute user={user}>
                <RoleGuard user={user} allow={['ADMIN']}>
                  <AdminRequestsPage user={user} onBack={() => navigate('/')} />
                </RoleGuard>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/team-builder"
            element={
              <ProtectedRoute user={user}>
                <RoleGuard user={user} allow={['ADMIN']}>
                  <TeamBuilderPage onBack={() => navigate('/admin/requests')} />
                </RoleGuard>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/taskbuilder"
            element={<Navigate to="/admin/team-builder" replace />}
          />
          <Route
            path="/gmail-result"
            element={
              <ProtectedRoute user={user}>
                <GmailResultPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to={user ? '/homepage' : '/login'} replace />} />
        </Routes>
      )}

      {activeModule === 'market' && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 'calc(100vh - 54px)',
            padding: 40,
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 56, marginBottom: 16 }}>🌍</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
            Market Intelligence
          </div>
          <div
            style={{
              fontSize: 14,
              color: 'var(--text2)',
              maxWidth: 420,
              lineHeight: 1.7,
              marginBottom: 24,
            }}
          >
            Competitor analysis, market trends, and growth opportunity tracking are coming soon.
            Switch to Sales Intelligence to explore the live dashboard.
          </div>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 20px',
              borderRadius: 10,
              background: 'rgba(5,150,105,.08)',
              border: '1px solid rgba(5,150,105,.2)',
              color: '#059669',
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            🚧 Under Development
          </div>
        </div>
      )}
    </div>
  )
}
