import { getOptionDisplayLabel, getSelectedOption } from '../utils/getSelectedOption'

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'

export function ReviewPicklistRadios({
  options,
  value,
  onChange,
  name,
  error,
  disabled,
  noTopMargin,
  payloadHighlightIds,
}) {
  const v = typeof value === 'string' ? value : ''
  const selectedOption = getSelectedOption(options, v)
  const selectedLabel = getOptionDisplayLabel(selectedOption)
  const hasActiveSelection = Boolean(v.trim())
  const payloadSet = new Set(Array.isArray(payloadHighlightIds) ? payloadHighlightIds.map(String) : [])
  return (
    <div role="radiogroup" aria-labelledby={name ? `${name}-legend` : undefined} aria-invalid={Boolean(error)} style={{ marginTop: noTopMargin ? 0 : 10 }}>
      {error ? (
        <div role="alert" style={{ fontSize: 11, fontWeight: 600, color: '#b91c1c', marginBottom: 8 }}>
          {error}
        </div>
      ) : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, alignItems: 'flex-start', width: '100%' }}>
        {options.map(o => {
          const optionLabel = getOptionDisplayLabel(o)
          const checkedByValue = selectedLabel !== '' && optionLabel === selectedLabel
          // Payload highlight is only useful before the user picks another value.
          // Keeping it visible after a selection makes two options look "selected".
          const payloadHighlighted = !hasActiveSelection && payloadSet.has(String(o.id))
          const checked = checkedByValue || (disabled && payloadHighlighted)
          return (
            <label
              key={o.id}
              style={{
                display: 'inline-flex',
                alignItems: 'flex-start',
                gap: 8,
                width: 'fit-content',
                maxWidth: '100%',
                boxSizing: 'border-box',
                cursor: disabled ? 'not-allowed' : 'pointer',
                padding: '6px 10px',
                borderRadius: 8,
                border: checked || payloadHighlighted ? `2px solid ${SI_ORANGE}` : '1px solid var(--border)',
                background: checked || payloadHighlighted ? 'rgba(232,83,46,.07)' : 'var(--bg3)',
                opacity: disabled ? 0.65 : 1,
                transition: 'border-color .12s, background .12s',
              }}
            >
              <input
                type="radio"
                name={name}
                checked={checked}
                disabled={disabled}
                onChange={() =>
                  onChange({
                    answer_id: String(o.id),
                    answer_value: optionLabel,
                  })
                }
                style={{ marginTop: 3, accentColor: SI_ORANGE, flexShrink: 0 }}
              />
              <span style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.4, fontWeight: checked ? 600 : 500 }}>
                {optionLabel.slice(0, 2000)}{optionLabel.length > 2000 ? '…' : ''}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

export function ReviewMultiCheckboxes({ options, value, onChange, error, disabled, noTopMargin, payloadHighlightIds }) {
  const arr = Array.isArray(value) ? value.map(String) : []
  const set = new Set(arr)
  const hasActiveSelection = set.size > 0
  const payloadSet = new Set(Array.isArray(payloadHighlightIds) ? payloadHighlightIds.map(String) : [])

  const toggle = (id) => {
    if (disabled) return
    const next = new Set(set)
    const sid = String(id)
    if (next.has(sid)) next.delete(sid)
    else next.add(sid)
    onChange([...next])
  }

  return (
    <div style={{ marginTop: noTopMargin ? 0 : 10 }} aria-invalid={Boolean(error)}>
      {error ? (
        <div role="alert" style={{ fontSize: 11, fontWeight: 600, color: '#b91c1c', marginBottom: 8 }}>
          {error}
        </div>
      ) : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, alignItems: 'flex-start', width: '100%' }}>
        {options.map(o => {
          const checked = set.has(String(o.id))
          // Match radio behavior: show payload highlight only until user starts selecting.
          const payloadHighlighted = !hasActiveSelection && payloadSet.has(String(o.id))
          return (
            <label
              key={o.id}
              style={{
                display: 'inline-flex',
                alignItems: 'flex-start',
                gap: 8,
                width: 'fit-content',
                maxWidth: '100%',
                boxSizing: 'border-box',
                cursor: disabled ? 'not-allowed' : 'pointer',
                padding: '6px 10px',
                borderRadius: 8,
                border: payloadHighlighted ? `2px solid ${SI_ORANGE}` : checked ? `2px solid ${SI_NAVY}` : '1px solid var(--border)',
                background: payloadHighlighted ? 'rgba(232,83,46,.07)' : checked ? 'rgba(27,38,79,.06)' : 'var(--bg3)',
                opacity: disabled ? 0.65 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={() => toggle(o.id)}
                style={{
                  marginTop: 3,
                  width: 16,
                  height: 16,
                  accentColor: SI_NAVY,
                  flexShrink: 0,
                  borderRadius: 4,
                }}
              />
              <span style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.4, fontWeight: checked ? 600 : 500 }}>
                {(o.text || '').slice(0, 2000)}{(o.text || '').length > 2000 ? '…' : ''}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}
