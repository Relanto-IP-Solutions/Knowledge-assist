import { badgeStyles } from '../data'

export default function Badge({ type, children, style = {} }) {
  const s = badgeStyles[type] || badgeStyles.pending
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      fontSize: 9, fontWeight: 700, padding: '2px 7px',
      borderRadius: 4, letterSpacing: '.3px', textTransform: 'uppercase',
      whiteSpace: 'nowrap', background: s.bg, color: s.color,
      border: `1px solid ${s.border}`, ...style
    }}>
      {children}
    </span>
  )
}
