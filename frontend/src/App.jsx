import { useState, useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom'
import Topbar from './components/Topbar'
import Landing from './components/Landing'
import QAPage from './components/QAPage'
import SourcesPage from './components/SourcesPage'
import GmailResultPage from './components/GmailResultPage'
import CreateOpportunityPage from './components/CreateOpportunityPage'
import LoginWithTheme from './components/Login'
import { subscribeAuth, signOutUser } from './services/authService'
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

function SourcesRoute({ user }) {
  const { oid } = useParams()
  const navigate = useNavigate()

  // Popup lands here after per-opportunity Gmail connect OAuth.
  useEffect(() => {
    if (!window.opener) return
    const params = new URLSearchParams(window.location.search)
    if (params.get('gmail_connect') !== 'success') return
    try {
      window.opener.postMessage(
        { type: 'gmail_oauth_result', gmailConnect: 'success', oid },
        window.location.origin,
      )
    } catch {
      /* noop */
    }
    window.close()
  }, [oid])

  return (
    <SourcesPage
      opportunityId={oid}
      opportunityName={oid}
      userEmail={user?.email || ''}
      onContinue={() => navigate('/qa/' + oid)}
      onBack={() => navigate('/')}
    />
  )
}

function QARoute({ onReviewSaved }) {
  const { oid } = useParams()
  const navigate = useNavigate()
  return (
    <QAPage
      oppId={oid}
      onBack={() => navigate('/')}
      onReviewSaved={onReviewSaved}
    />
  )
}

function CreateRoute({ user }) {
  const navigate = useNavigate()
  return (
    <CreateOpportunityPage
      user={user}
      onBack={() => navigate('/')}
      onCreated={(id) => navigate('/sources/' + id)}
    />
  )
}

export default function App() {
  const navigate = useNavigate()
  const [user, setUser] = useState(null)
  const [authReady, setAuthReady] = useState(false)
  const [activeModule, setActiveModule] = useState('sales')
  const [landingRefreshKey, setLandingRefreshKey] = useState(0)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'relanto')
  }, [])

  useEffect(() => {
    return subscribeAuth((nextUser) => {
      setUser(nextUser)
      setAuthReady(true)
    })
  }, [])

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
        if (oid) navigate('/sources/' + oid)
        else navigate('/')
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
        navigate('/')
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

        navigate('/sources/' + msg.oid)
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [navigate])

  const handleLogin = (loggedInUser, module) => {
    setUser(loggedInUser)
    if (module) setActiveModule(module)
    navigate('/')
  }

  const handleLogout = async () => {
    await signOutUser()
    setUser(null)
    navigate('/')
  }

  const switchModule = (mod) => {
    if (!mod.enabled) return
    setActiveModule(mod.id)
    navigate('/')
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
        Signing in...
      </div>
    )
  }

  if (!user) {
    return <LoginWithTheme onLogin={handleLogin} theme="relanto" />
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Topbar
        activeModule={activeModule}
        onLogoClick={() => navigate('/')}
        onSwitchModule={switchModule}
        user={user}
        onLogout={handleLogout}
      />

      {activeModule === 'sales' && (
        <Routes>
          <Route
            path="/"
            element={
              <Landing
                key={landingRefreshKey}
                onOpenOpp={(id) => navigate('/sources/' + id)}
                userEmail={user?.email || ''}
                refreshKey={landingRefreshKey}
                onOpportunitiesRefresh={bumpDashboardRefresh}
              />
            }
          />
          <Route path="/sources/:oid" element={<SourcesRoute user={user} />} />
          <Route path="/qa/:oid" element={<QARoute onReviewSaved={bumpDashboardRefresh} />} />
          <Route path="/create" element={<CreateRoute user={user} />} />
          <Route path="/gmail-result" element={<GmailResultPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
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
