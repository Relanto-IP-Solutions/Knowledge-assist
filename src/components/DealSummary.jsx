/**
 * DealSummaryPanel — extracted as a standalone component.
 * Currently disabled in QAPage. To re-enable, import and render
 * where `activeSectionData.isSummary` is true.
 */
export default function DealSummaryPanel({ opp, sec, sections, qState }) {
  const nonSummarySections = sections.filter(s => !s.isSummary)

  const Vital = ({ label, value, mono }) => (
    <div style={{ flex: 1, background: 'rgba(255,255,255,.03)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', fontFamily: mono ? 'monospace' : 'var(--font)' }}>{value}</div>
    </div>
  )

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
        <div style={{ width: 36, height: 36, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, flexShrink: 0, background: sec.bg }}>📊</div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)', letterSpacing: '-.3px' }}>Deal Summary</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>AI-generated overview · updated from latest signals</div>
        </div>
      </div>

      {/* Vitals */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Vital label="TCV" value={opp?.value} mono />
        <Vital label="Stage" value={opp?.stage} />
        <Vital label="Owner" value={opp?.owner} />
        <Vital label="Target Close" value={opp?.closeDate} />
        <Vital label="Days in Stage" value={`${opp?.days}d`} />
      </div>

      {/* Deal Likelihood Score */}
      {opp?.score != null && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
          <div style={{ background: 'rgba(255,255,255,.03)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 16, flex: 1 }}>
            <div style={{ position: 'relative', width: 54, height: 54, flexShrink: 0 }}>
              <svg width="54" height="54" viewBox="0 0 54 54">
                <circle cx="27" cy="27" r="22" fill="none" stroke="rgba(255,255,255,.06)" strokeWidth="5" />
                <circle cx="27" cy="27" r="22" fill="none"
                  stroke={opp.score >= 70 ? '#56D364' : opp.score >= 45 ? '#E3B341' : '#FF7B72'}
                  strokeWidth="5" strokeLinecap="round"
                  strokeDasharray={`${(opp.score / 100) * 138.2} 138.2`}
                  transform="rotate(-90 27 27)" />
              </svg>
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>{opp.score}</div>
            </div>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 3 }}>Deal Likelihood Score</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.3 }}>{opp.score}th percentile</div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>vs. all open deals · 300+ signals</div>
            </div>
          </div>
          {opp.warnings?.length > 0 && (
            <div style={{ background: 'rgba(248,81,73,.04)', border: '1px solid rgba(248,81,73,.18)', borderRadius: 12, padding: '14px 16px', flex: 1 }}>
              <div style={{ fontSize: 9, fontWeight: 800, color: '#FF7B72', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 10 }}>{opp.warnings.length} Active Warning{opp.warnings.length > 1 ? 's' : ''}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {opp.warnings.map((w, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11, color: 'var(--text1)' }}>
                    <span style={{ fontSize: 12 }}>{w.icon}</span>
                    <span style={{ color: w.color, fontWeight: 600 }}>{w.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {opp.warnings?.length === 0 && (
            <div style={{ background: 'rgba(63,185,80,.04)', border: '1px solid rgba(63,185,80,.18)', borderRadius: 12, padding: '14px 16px', flex: 1, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 20 }}>✅</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#56D364' }}>No Active Warnings</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>All signals healthy</div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* AI Narrative */}
      <div style={{ background: 'rgba(37,99,235,.06)', border: '1px solid rgba(37,99,235,.20)', borderRadius: 12, padding: '14px 16px', marginBottom: 14 }}>
        <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--p)', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ background: 'linear-gradient(135deg,rgba(37,99,235,.12),rgba(79,70,229,.10))', border: '1px solid rgba(37,99,235,.22)', borderRadius: 4, padding: '1px 6px' }}>✦ Knowledge Assistant · AI Narrative</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text1)', lineHeight: 1.7 }}>{sec.narrative}</div>
      </div>

      {/* Risks & Strengths */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <div style={{ flex: 1, background: 'rgba(248,81,73,.04)', border: '1px solid rgba(248,81,73,.18)', borderRadius: 12, padding: '12px 14px' }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: '#FF7B72', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 10 }}>Risk Signals</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {sec.risks.map((r, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, fontSize: 12, color: 'var(--text1)', lineHeight: 1.4 }}>
                <span style={{ color: '#FF7B72', flexShrink: 0, marginTop: 1 }}>●</span>{r}
              </div>
            ))}
          </div>
        </div>
        {sec.strengths.length > 0 && (
          <div style={{ flex: 1, background: 'rgba(63,185,80,.04)', border: '1px solid rgba(63,185,80,.18)', borderRadius: 12, padding: '12px 14px' }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: '#56D364', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 10 }}>Strengths</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {sec.strengths.map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, fontSize: 12, color: 'var(--text1)', lineHeight: 1.4 }}>
                  <span style={{ color: '#56D364', flexShrink: 0, marginTop: 1 }}>✓</span>{s}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Section Coverage */}
      {nonSummarySections.length > 0 && (
        <div style={{ background: 'rgba(255,255,255,.02)', border: '1px solid var(--border)', borderRadius: 12, padding: '12px 14px', marginBottom: 14 }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 12 }}>Qualification Coverage</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {nonSummarySections.map(s => {
              const qs = s.signals.filter(sig => sig.type === 'ai').flatMap(sig => sig.qs)
              const total = qs.length
              const ans = qs.filter(q => qState[q.id]?.status !== 'pending').length
              const pct = total ? Math.round(ans / total * 100) : 0
              return (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 14, flexShrink: 0 }}>{s.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text1)' }}>{s.title}</span>
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{ans}/{total}</span>
                    </div>
                    <div style={{ height: 4, background: 'var(--bg4)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${pct}%`, background: s.color, borderRadius: 2, transition: 'width .3s' }} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Next Steps / To-dos */}
      {opp?.todos?.length > 0 && (
        <div style={{ background: 'rgba(255,255,255,.02)', border: '1px solid var(--border)', borderRadius: 12, padding: '12px 14px', marginBottom: 14 }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>Next Steps</span>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>{opp.todos.filter(t => !t.done).length} open · {opp.todos.filter(t => t.done).length} done</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {opp.todos.map((t, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 9 }}>
                <div style={{ width: 16, height: 16, borderRadius: 4, border: `1.5px solid ${t.done ? '#56D364' : t.priority === 'P0' ? '#FF7B72' : '#E3B341'}`, background: t.done ? 'rgba(63,185,80,.15)' : 'transparent', flexShrink: 0, marginTop: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#56D364' }}>
                  {t.done ? '✓' : ''}
                </div>
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 12, color: t.done ? 'var(--text3)' : 'var(--text1)', textDecoration: t.done ? 'line-through' : 'none', lineHeight: 1.4 }}>{t.text}</span>
                </div>
                <span style={{ fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 4, flexShrink: 0, marginTop: 2,
                  background: t.priority === 'P0' ? 'rgba(248,81,73,.1)' : 'rgba(210,153,34,.1)',
                  color: t.priority === 'P0' ? '#FF7B72' : '#E3B341',
                  border: `1px solid ${t.priority === 'P0' ? 'rgba(248,81,73,.3)' : 'rgba(210,153,34,.3)'}` }}>
                  {t.priority}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
