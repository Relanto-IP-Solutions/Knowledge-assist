import { useCallback, useEffect, useRef, useState } from 'react'
import { checkNameExists, createOpportunityRequest } from '../services/requestsApi'

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'
const NAME_VALID_RE = /^[A-Za-z0-9 -]*$/ // allows empty while typing

export default function CreateOpportunityPage({ onBack }) {
  const [name, setName] = useState('')
  const [charError, setCharError] = useState(null)
  const [nameExists, setNameExists] = useState(false)
  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [submitted, setSubmitted] = useState(false)
  const debounceRef = useRef(null)

  const runNameCheck = useCallback(async (value) => {
    const trimmed = value.trim()
    if (!trimmed || !NAME_VALID_RE.test(value)) {
      setNameExists(false)
      setChecking(false)
      return
    }
    setChecking(true)
    try {
      const exists = await checkNameExists(trimmed)
      setNameExists(exists)
    } catch {
      setNameExists(false)
    } finally {
      setChecking(false)
    }
  }, [])

  const handleNameChange = (e) => {
    const val = e.target.value
    setName(val)
    setSubmitError(null)

    if (!NAME_VALID_RE.test(val)) {
      setCharError('Only letters, numbers, hyphens, and spaces are allowed.')
    } else {
      setCharError(null)
    }

    // Debounce the availability check (400ms)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runNameCheck(val), 400)
  }

  useEffect(() => () => clearTimeout(debounceRef.current), [])

  const trimmed = name.trim()
  const isDisabled = busy || checking || !trimmed || !!charError || nameExists

  const handleSubmit = async () => {
    if (isDisabled) return
    setBusy(true)
    setSubmitError(null)
    try {
      await createOpportunityRequest(trimmed)
      setSubmitted(true)
    } catch (e) {
      setSubmitError(e.message || 'Failed to submit request.')
    } finally {
      setBusy(false)
    }
  }

  const card = {
    borderRadius: 16,
    border: '1px solid rgba(27,38,79,.1)',
    background: '#fff',
    boxShadow: '0 1px 2px rgba(15,23,42,.04)',
  }

  if (submitted) {
    return (
      <div style={{
        minHeight: 'calc(100vh - 56px)',
        background: 'var(--bg, #f4f6f9)',
        padding: '24px 20px 48px',
        fontFamily: 'var(--font)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
      }}>
        <div style={{ maxWidth: 520, width: '100%', marginTop: 48 }}>
          <div style={{ ...card, padding: '36px 32px', textAlign: 'center' }}>
            <div style={{
              width: 52, height: 52, borderRadius: '50%',
              background: 'rgba(5,150,105,.1)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 18px',
            }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </div>
            <h2 style={{ margin: '0 0 10px', fontSize: 20, fontWeight: 800, color: SI_NAVY }}>
              Request submitted
            </h2>
            <p style={{ margin: '0 0 24px', fontSize: 13, color: '#64748b', lineHeight: 1.6 }}>
              Your opportunity request for <strong style={{ color: SI_NAVY }}>{trimmed}</strong> is pending admin approval.
              You'll be notified once it's reviewed.
            </p>
            <button
              type="button"
              onClick={onBack}
              style={{
                padding: '11px 24px', borderRadius: 10, border: 'none',
                background: SI_NAVY, color: '#fff', fontSize: 13,
                fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font)',
              }}
            >
              Back to dashboard
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{
      minHeight: 'calc(100vh - 56px)',
      background: 'var(--bg, #f4f6f9)',
      padding: '24px 20px 48px',
      fontFamily: 'var(--font)',
    }}>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 4px 8px 0', border: 'none', background: 'none',
            cursor: 'pointer', fontSize: 13, fontWeight: 600,
            color: 'var(--text2)', marginBottom: 20, fontFamily: 'var(--font)',
          }}
        >
          <span aria-hidden style={{ fontSize: 16, lineHeight: 1 }}>←</span>
          Back
        </button>

        <header style={{ marginBottom: 24 }}>
          <h1 style={{
            fontSize: 'clamp(1.5rem, 4vw, 1.85rem)', fontWeight: 800,
            letterSpacing: '-0.03em', color: SI_NAVY, margin: 0, lineHeight: 1.2,
          }}>
            Request an opportunity
          </h1>
          <p style={{ fontSize: 15, color: 'var(--text2)', lineHeight: 1.55, margin: '10px 0 0', maxWidth: 520 }}>
            Submit your request for admin review. Use letters, numbers, hyphens, and spaces only.
          </p>
        </header>

        {submitError && (
          <div role="alert" aria-live="polite" style={{
            marginBottom: 20, padding: '12px 14px', borderRadius: 10,
            background: '#FEF2F2', border: '1px solid #FECACA',
            color: '#991B1B', fontSize: 14, fontWeight: 500, lineHeight: 1.45,
          }}>
            {submitError}
          </div>
        )}

        <section style={{ ...card, padding: '24px 22px 26px' }}>
          <h2 style={{
            fontSize: 11, fontWeight: 800, letterSpacing: '0.1em',
            color: SI_ORANGE, margin: '0 0 16px',
          }}>
            DETAILS
          </h2>
          <label htmlFor="create-opp-name" style={{
            display: 'block', fontSize: 13, fontWeight: 600,
            color: SI_NAVY, marginBottom: 6,
          }}>
            Name <span style={{ color: SI_ORANGE }}>*</span>
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="create-opp-name"
              value={name}
              onChange={handleNameChange}
              onKeyDown={(e) => { if (e.key === 'Enter' && !isDisabled) handleSubmit() }}
              placeholder="e.g. DocuSign Relanto KA"
              autoComplete="off"
              disabled={busy}
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '12px 14px', paddingRight: 40,
                borderRadius: 10, fontSize: 15, fontFamily: 'var(--font)',
                border: `1px solid ${charError || nameExists ? '#FECACA' : 'var(--border)'}`,
                background: 'var(--bg2, #fff)',
                outline: 'none',
                transition: 'border-color .15s',
              }}
              onFocus={e => { e.target.style.borderColor = charError || nameExists ? '#f87171' : SI_ORANGE; e.target.style.boxShadow = `0 0 0 2px ${SI_ORANGE}30` }}
              onBlur={e => { e.target.style.borderColor = charError || nameExists ? '#FECACA' : 'var(--border)'; e.target.style.boxShadow = '' }}
            />
            {/* Checking spinner */}
            {checking && (
              <span style={{
                position: 'absolute', right: 12, top: '50%',
                transform: 'translateY(-50%)',
                width: 16, height: 16, border: '2px solid #e2e8f0',
                borderTopColor: SI_NAVY, borderRadius: '50%',
                animation: 'spin .6s linear infinite',
                display: 'inline-block',
              }} />
            )}
          </div>
          <style>{`@keyframes spin { to { transform: translateY(-50%) rotate(360deg); } }`}</style>

          {/* Validation messages */}
          {charError && (
            <p style={{ margin: '6px 0 0', fontSize: 12, color: '#b91c1c', fontWeight: 500 }}>
              {charError}
            </p>
          )}
          {!charError && nameExists && (
            <p style={{ margin: '6px 0 0', fontSize: 12, color: '#b91c1c', fontWeight: 500 }}>
              This opportunity name already exists or has a pending request.
            </p>
          )}
          {!charError && !nameExists && trimmed && !checking && (
            <p style={{ margin: '6px 0 0', fontSize: 12, color: '#059669', fontWeight: 500 }}>
              Name is available.
            </p>
          )}

          <button
            type="button"
            disabled={isDisabled}
            onClick={handleSubmit}
            aria-busy={busy}
            style={{
              width: '100%', marginTop: 20,
              padding: '14px 20px', borderRadius: 10, border: 'none',
              background: isDisabled ? '#94a3b8' : SI_ORANGE,
              color: '#fff', fontSize: 15, fontWeight: 700,
              cursor: isDisabled ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--font)',
              boxShadow: isDisabled ? 'none' : '0 2px 8px rgba(232,83,46,.25)',
              transition: 'background .15s',
            }}
          >
            {busy ? 'Submitting…' : checking ? 'Checking…' : 'Submit request'}
          </button>
        </section>
      </div>
    </div>
  )
}
