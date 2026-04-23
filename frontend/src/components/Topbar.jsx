import { useEffect, useRef, useState } from 'react'
import { MODULES } from '../App'

export default function Topbar({ activeModule, onLogoClick, onSwitchModule, user, onLogout, onNavigate }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const name = user?.name || 'Knowledge User'
  const role = user?.role || 'Analyst'
  const avatar = user?.avatar || 'KA'

  const navText = 'var(--si-nav-text, var(--text0))'
  const navMuted = 'var(--si-nav-muted, var(--text2))'
  const navBorder = 'var(--si-nav-border, var(--border))'
  /** Active tab underline: always navy (not theme accent orange). */
  const tabActiveBorder = 'var(--si-navy, #1B264F)'

  return (
    <header
      style={{
        background: 'var(--si-topbar-bg, var(--topbar-bg))',
        backdropFilter: 'blur(14px)',
        borderBottom: `1px solid ${navBorder}`,
        minHeight: 56,
        display: 'flex',
        alignItems: 'stretch',
        padding: '0 22px 0 20px',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        gap: 8,
      }}
    >
      {/* Brand */}
      <button
        type="button"
        onClick={onLogoClick}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '4px 0',
          flexShrink: 0,
          fontFamily: 'var(--font)',
          alignSelf: 'center',
        }}
      >
        <img src="/relanto-logo.png" alt="" style={{ height: 26, objectFit: 'contain', borderRadius: 4, opacity: 0.95, alignSelf: 'center' }} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: '0.14em',
            color: navText,
            textAlign: 'left',
            lineHeight: 1.2,
            maxWidth: 140,
            alignSelf: 'center',
          }}
        >
          KNOWLEDGE
          <br />
          ASSIST
        </span>
      </button>

      <div style={{ width: 1, height: 28, background: navBorder, flexShrink: 0, margin: '0 6px', alignSelf: 'center' }} />

      {/* Module tabs — underline sits on the header bottom edge */}
      <nav style={{ display: 'flex', alignItems: 'stretch', flex: 1, gap: 0, minWidth: 0 }}>
        {MODULES.map((mod) => {
          const isActive = mod.id === activeModule
          return (
            <button
              key={mod.id}
              type="button"
              onClick={() => onSwitchModule(mod)}
              title={!mod.enabled ? 'Coming soon' : undefined}
              disabled={!mod.enabled}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '0 16px',
                margin: 0,
                background: 'none',
                border: 'none',
                borderBottom: isActive ? `3px solid ${tabActiveBorder}` : '3px solid transparent',
                cursor: mod.enabled ? 'pointer' : 'not-allowed',
                fontFamily: 'var(--font)',
                transition: 'border-color .15s, color .15s',
                boxSizing: 'border-box',
              }}
            >
              {mod.icon && <span style={{ fontSize: 14 }}>{mod.icon}</span>}
              <span
                style={{
                  fontSize: 13,
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? navText : mod.enabled ? navMuted : 'var(--text3)',
                  letterSpacing: '-0.02em',
                  whiteSpace: 'nowrap',
                }}
              >
                {mod.label}
              </span>
            </button>
          )
        })}
      </nav>

      {/* Right: profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, alignSelf: 'center' }}>
        <div ref={menuRef} style={{ position: 'relative' }}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              border: `1px solid ${navBorder}`,
              background: menuOpen ? 'var(--si-icon-bg-hover, rgba(27,38,79,.08))' : 'var(--si-icon-bg, rgba(255,255,255,.8))',
              color: navText,
              borderRadius: 999,
              padding: '3px 12px 3px 3px',
              fontFamily: 'var(--font)',
              transition: 'all .15s',
              cursor: 'pointer',
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'var(--avatar-bg)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 10,
                fontWeight: 800,
                color: '#fff',
              }}
            >
              {avatar}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1.15, textAlign: 'left' }}>
              <span style={{ fontSize: 11, fontWeight: 700 }}>{name}</span>
              <span style={{ fontSize: 9, color: navMuted }}>{role}</span>
            </div>
            <span style={{ fontSize: 8, color: navMuted }}>{menuOpen ? '▲' : '▼'}</span>
          </button>

          {menuOpen && (
            <div
              style={{
                position: 'absolute',
                top: 'calc(100% + 8px)',
                right: 0,
                minWidth: 220,
                background: 'var(--bg2)',
                border: '1px solid var(--border)',
                borderRadius: 12,
                boxShadow: '0 12px 32px rgba(15,23,42,.14)',
                overflow: 'hidden',
                zIndex: 220,
              }}
            >
              <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{name}</div>
                <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{user?.email || 'user@company.com'}</div>
              </div>
              {['Profile settings', 'Help & support'].map((label) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '10px 14px',
                    border: 'none',
                    borderBottom: '1px solid var(--border)',
                    background: 'transparent',
                    color: 'var(--text1)',
                    fontSize: 12,
                    fontFamily: 'var(--font)',
                    cursor: 'pointer',
                  }}
                >
                  {label}
                </button>
              ))}
              {/* Admin Panel section */}
              <div style={{ padding: '8px 14px 4px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 6 }}>Admin Panel</div>
                {[
                  { label: 'Opportunity Requests', path: '/admin/requests' },
                  { label: 'Team Builder', path: '/admin/team-builder' },
                ].map((item) => (
                  <button
                    key={item.path}
                    type="button"
                    onClick={() => { setMenuOpen(false); onNavigate?.(item.path) }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '8px 0',
                      border: 'none',
                      background: 'transparent',
                      color: 'var(--text1)',
                      fontSize: 12,
                      fontFamily: 'var(--font)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    {item.label === 'Opportunity Requests' && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
                    )}
                    {item.label === 'Team Builder' && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                    )}
                    {item.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false)
                  onLogout?.()
                }}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '10px 14px',
                  border: 'none',
                  background: 'transparent',
                  color: '#DC2626',
                  fontSize: 12,
                  fontWeight: 700,
                  fontFamily: 'var(--font)',
                  cursor: 'pointer',
                }}
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
