import { useState } from 'react'
import { createOpportunity } from '../services/opportunitiesApi'

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'

const inputFocus = {
  outline: 'none',
  boxShadow: `0 0 0 2px ${SI_ORANGE}40`,
  borderColor: SI_ORANGE,
}

/**
 * @param {{ user: { email?: string }, onBack: () => void, onCreated: (opportunityId: string) => void }} props
 */
export default function CreateOpportunityPage({ user, onBack, onCreated }) {
  const [name, setName] = useState('New Opportunity')
  const [formBusy, setFormBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleCreate = async () => {
    setError(null)
    const n = String(name ?? '').trim() || 'New Opportunity'
    const payload = { name: n }
    console.log('[Create Opportunity Clicked]')
    console.log('[Create Opportunity Payload]', payload)
    setFormBusy(true)
    try {
      const { opportunity_id: id } = await createOpportunity(payload)
      console.log('[Create Opportunity Success]', { opportunityId: id })
      onCreated(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setFormBusy(false)
    }
  }

  const card = {
    borderRadius: 16,
    border: '1px solid rgba(27,38,79,.1)',
    background: '#fff',
    boxShadow: '0 1px 2px rgba(15,23,42,.04)',
  }

  return (
    <div
      style={{
        minHeight: 'calc(100vh - 56px)',
        background: 'var(--bg, #f4f6f9)',
        padding: '24px 20px 48px',
        fontFamily: 'var(--font)',
      }}
    >
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '8px 4px 8px 0',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text2)',
            marginBottom: 20,
            fontFamily: 'var(--font)',
          }}
        >
          <span aria-hidden style={{ fontSize: 16, lineHeight: 1 }}>←</span>
          Back
        </button>

        <header style={{ marginBottom: 24 }}>
          <h1
            style={{
              fontSize: 'clamp(1.5rem, 4vw, 1.85rem)',
              fontWeight: 800,
              letterSpacing: '-0.03em',
              color: SI_NAVY,
              margin: 0,
              lineHeight: 1.2,
            }}
          >
            Create opportunity
          </h1>
          <p style={{ fontSize: 15, color: 'var(--text2)', lineHeight: 1.55, margin: '10px 0 0', maxWidth: 520 }}>
            Enter the basic details and create the opportunity.
          </p>
        </header>

        {error && (
          <div
            role="alert"
            aria-live="polite"
            style={{
              marginBottom: 20,
              padding: '12px 14px',
              borderRadius: 10,
              background: '#FEF2F2',
              border: '1px solid #FECACA',
              color: '#991B1B',
              fontSize: 14,
              fontWeight: 500,
              lineHeight: 1.45,
            }}
          >
            {error}
          </div>
        )}

        <section aria-labelledby="opp-form-heading" style={{ ...card, padding: '24px 22px 26px' }}>
          <h2
            id="opp-form-heading"
            style={{
              fontSize: 11,
              fontWeight: 800,
              letterSpacing: '0.1em',
              color: SI_ORANGE,
              margin: '0 0 16px',
            }}
          >
            DETAILS
          </h2>
          <label htmlFor="create-opp-name" style={{ display: 'block', fontSize: 13, fontWeight: 600, color: SI_NAVY, marginBottom: 6 }}>
            Name <span style={{ color: SI_ORANGE }}>*</span>
          </label>
          <input
            id="create-opp-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. Acme Corp — Enterprise renewal"
            autoComplete="organization"
            onFocus={e => Object.assign(e.target.style, inputFocus)}
            onBlur={e => {
              e.target.style.boxShadow = ''
              e.target.style.borderColor = 'var(--border)'
            }}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '12px 14px',
              borderRadius: 10,
              border: '1px solid var(--border)',
              fontSize: 15,
              fontFamily: 'var(--font)',
              marginBottom: 16,
              background: 'var(--bg2, #fff)',
              transition: 'box-shadow .15s, border-color .15s',
            }}
          />
          <button
            type="button"
            disabled={formBusy}
            onClick={handleCreate}
            aria-busy={formBusy}
            style={{
              width: '100%',
              padding: '14px 20px',
              borderRadius: 10,
              border: 'none',
              background: SI_ORANGE,
              color: '#fff',
              fontSize: 15,
              fontWeight: 700,
              cursor: formBusy ? 'wait' : 'pointer',
              fontFamily: 'var(--font)',
              boxShadow: '0 2px 8px rgba(232,83,46,.25)',
            }}
          >
            {formBusy ? 'Creating…' : 'Create opportunity'}
          </button>
        </section>
      </div>
    </div>
  )
}
