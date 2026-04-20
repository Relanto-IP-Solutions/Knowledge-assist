export function OpportunityAnswersSkeleton({ count = 4 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, animation: 'fadeIn .2s ease' }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            borderRadius: 10,
            border: '1px solid var(--border)',
            background: 'var(--bg2)',
            padding: 14,
            height: 112,
            backgroundImage: 'linear-gradient(90deg, var(--bg3) 0%, var(--bg4) 50%, var(--bg3) 100%)',
            backgroundSize: '200% 100%',
            animation: 'pulse 1.2s ease-in-out infinite',
          }}
        />
      ))}
      <style>{`
        @keyframes pulse {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  )
}
