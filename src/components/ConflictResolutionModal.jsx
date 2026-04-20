import { useCallback, useEffect, useMemo, useState } from 'react'
import { classifyApiSourceType } from '../utils/mapApiAnswerToQuestionCard'
import { CONFLICT_SRC_MODAL, conflictOptionHeading } from '../utils/conflictUi'
import { parseSerializedListAnswerValue } from '../utils/opportunityAnswerRowToReviewQuestion'
import { CitationBlock } from './ApiAnswerCard'
import { SourceIcon } from './SourceIcons'

function ModalBtn({ children, onClick, ghost, primary, disabled }) {
  const [hov, setHov] = useState(false)
  const base = {
    padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none', transition: 'all .15s',
    fontFamily: 'var(--font)', display: 'inline-flex', alignItems: 'center', gap: 4,
    opacity: disabled ? 0.5 : 1,
  }
  const s = ghost
    ? { background: hov ? 'rgba(37,99,235,.10)' : 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)' }
    : primary
      ? { background: hov ? 'var(--p2)' : 'var(--p)', color: '#fff', border: 'none', fontWeight: 700 }
      : {}
  return (
    <button type="button" style={{ ...base, ...s }} onClick={disabled ? undefined : onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      {children}
    </button>
  )
}

function normalizeAnswerValue(value) {
  if (Array.isArray(value)) {
    return value.map(v => String(v ?? '').trim()).filter(Boolean)
  }
  const raw = String(value ?? '').trim()
  if (!raw) return []
  if (raw.startsWith('[')) {
    try {
      const parsed = parseSerializedListAnswerValue(raw)
      const out = parsed.map(v => String(v ?? '').trim()).filter(Boolean)
      if (out.length > 0) return out
    } catch {
      // Fall through to plain scalar formatting.
    }
  }
  return [raw]
}

function answersMatchForConflictSelection(stored, conflictAnswer) {
  const a = normalizeAnswerValue(stored)
  const b = normalizeAnswerValue(conflictAnswer)
  if (a.length && b.length && a.length === b.length) {
    return a.every((v, i) => String(v).trim() === String(b[i]).trim())
  }
  const sa = String(stored ?? '').trim()
  const sb = String(conflictAnswer ?? '').trim()
  if (!sa && !sb) return false
  return sa === sb || sa.toLowerCase() === sb.toLowerCase()
}

/**
 * Find index in `fullConflicts` matching a prior user choice (text and/or answer_id).
 */
function findMatchingConflictFullIndex(fullConflicts, { initialSelectedAnswer, initialSelectedAnswerId }) {
  if (!Array.isArray(fullConflicts) || fullConflicts.length === 0) return null
  const idRaw = initialSelectedAnswerId != null ? String(initialSelectedAnswerId).trim() : ''
  if (idRaw) {
    for (let i = 0; i < fullConflicts.length; i++) {
      const c = fullConflicts[i]
      if (c?.answer_id != null && String(c.answer_id).trim() === idRaw) return i
      if (String(c?.answer ?? '').trim() === idRaw) return i
    }
  }
  const ans = initialSelectedAnswer
  if (ans == null || String(ans).trim() === '') return null
  for (let i = 0; i < fullConflicts.length; i++) {
    if (answersMatchForConflictSelection(ans, fullConflicts[i]?.answer)) return i
  }
  return null
}

function mapFullIndexToDisplayedIndex(fullConflicts, displayedConflicts, fullIndex) {
  if (fullIndex == null || fullIndex < 0 || !Array.isArray(displayedConflicts)) return null
  const row = fullConflicts[fullIndex]
  if (!row) return null
  const di = displayedConflicts.findIndex(d => {
    if (d === row) return true
    if (d?.conflictIndex != null && row?.conflictIndex != null && d.conflictIndex === row.conflictIndex) {
      return true
    }
    return answersMatchForConflictSelection(d?.answer, row?.answer)
  })
  return di >= 0 ? di : null
}

/** Index of the AI / primary row in the full conflicts array (defaults to first row). */
function findPrimaryRecommendationFullIndex(fullConflicts) {
  if (!Array.isArray(fullConflicts) || fullConflicts.length === 0) return null
  const i = fullConflicts.findIndex(c => c?.role === 'primary')
  return i >= 0 ? i : 0
}

/**
 * preferPrimaryRecommendation (default true): when no prior selection matches, pre-select the primary/AI row.
 * @param {{
 *   open: boolean,
 *   onClose: () => void,
 *   questionText: string,
 *   conflicts: Array<{ answer: string, answer_id?: string | null, conf?: number, srcType?: string, qid?: string, role?: string, conflictIndex?: number, citations?: unknown[] }>,
 *   onConfirm: (chosen: { answer: string, answer_id?: string | null, role?: string, conflictIndex?: number }) => void,
 *   stepLabel?: string | null,
 *   omitPrimaryRecommendation?: boolean,
 *   initialSelectedAnswer?: string | null,
 *   initialSelectedAnswerId?: string | null,
 *   preferPrimaryRecommendation?: boolean,
 *   onPrev?: () => void,
 *   onNext?: () => void,
 *   hasPrev?: boolean,
 *   hasNext?: boolean,
 * }} props
 */
export function ConflictResolutionModal({
  open,
  onClose,
  questionText,
  conflicts,
  onConfirm,
  stepLabel,
  omitPrimaryRecommendation = false,
  initialSelectedAnswer = null,
  initialSelectedAnswerId = null,
  preferPrimaryRecommendation = true,
  onPrev = null,
  onNext = null,
  hasPrev = false,
  hasNext = false,
}) {
  const [selected, setSelected] = useState(null)
  /** Which conflict rows have the citations panel expanded (optional detail). */
  const [citationPanelsOpen, setCitationPanelsOpen] = useState(() => new Set())

  const displayedConflicts = useMemo(() => {
    if (!conflicts?.length) return []
    if (!omitPrimaryRecommendation) return conflicts
    const f = conflicts.filter(c => c.role !== 'primary')
    return f.length >= 1 ? f : conflicts
  }, [conflicts, omitPrimaryRecommendation])

  useEffect(() => {
    if (!open) return
    setCitationPanelsOpen(new Set())
    const full = conflicts || []
    let fullIdx = findMatchingConflictFullIndex(full, {
      initialSelectedAnswer,
      initialSelectedAnswerId,
    })
    if (fullIdx == null && preferPrimaryRecommendation) {
      fullIdx = findPrimaryRecommendationFullIndex(full)
    }
    let displayedIdx = mapFullIndexToDisplayedIndex(full, displayedConflicts, fullIdx)
    if (displayedIdx == null && preferPrimaryRecommendation && displayedConflicts.length > 0) {
      displayedIdx = 0
    }
    setSelected(displayedIdx != null ? displayedIdx : null)
  }, [
    open,
    questionText,
    conflicts,
    displayedConflicts,
    omitPrimaryRecommendation,
    initialSelectedAnswer,
    initialSelectedAnswerId,
    preferPrimaryRecommendation,
  ])

  const toggleCitationsPanel = index => {
    setCitationPanelsOpen(prev => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  /** When not in bulk multi-question mode, footer nav moves between competing responses for this question. */
  const useInternalOptionNav = onPrev == null && onNext == null && displayedConflicts.length > 1
  const goOptionPrev = useCallback(() => {
    setSelected(s => Math.max(0, (s ?? 0) - 1))
  }, [])
  const goOptionNext = useCallback(() => {
    setSelected(s => Math.min(displayedConflicts.length - 1, (s ?? 0) + 1))
  }, [displayedConflicts.length])

  const showNavArrows = Boolean(onPrev || onNext || useInternalOptionNav)
  const prevHandler = onPrev || (useInternalOptionNav ? goOptionPrev : null)
  const nextHandler = onNext || (useInternalOptionNav ? goOptionNext : null)
  const prevNavDisabled = onPrev != null ? !hasPrev : useInternalOptionNav ? (selected ?? 0) <= 0 : true
  const nextNavDisabled = onNext != null ? !hasNext : useInternalOptionNav ? (selected ?? 0) >= displayedConflicts.length - 1 : true
  const prevAria = useInternalOptionNav ? 'Previous competing response' : 'Previous conflict question'
  const nextAria = useInternalOptionNav ? 'Next competing response' : 'Next conflict question'

  if (!open || !displayedConflicts.length) return null

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 10000,
        background: 'rgba(15,23,42,.55)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        animation: 'fadeIn .15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '90%', maxWidth: 680, maxHeight: '85vh', overflow: 'auto',
          background: 'var(--bg2)', borderRadius: 16,
          border: '1px solid var(--border)',
          boxShadow: '0 25px 60px rgba(0,0,0,.25), 0 0 0 1px rgba(255,255,255,.05)',
        }}
      >
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '18px 24px',
          borderBottom: '1px solid var(--border)',
        }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#EA580C" strokeWidth="2" strokeLinecap="round" aria-hidden>
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>Resolve conflict</div>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>
              {stepLabel ? `${stepLabel} · ` : ''}{displayedConflicts.length} competing response{displayedConflicts.length !== 1 ? 's' : ''} — choose one to apply.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              width: 30, height: 30, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid var(--border)', background: 'var(--bg3)', cursor: 'pointer', flexShrink: 0,
            }}
            aria-label="Close"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text2)" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <div style={{ padding: '14px 24px', background: 'var(--bg3)', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)', lineHeight: 1.5 }}>{questionText}</div>
        </div>

        <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {displayedConflicts.map((c, i) => {
            const isSelected = selected === i
            const answerLines = normalizeAnswerValue(c?.answer)
            const c0 = Array.isArray(c.citations) && c.citations[0] ? c.citations[0] : null
            const brand = c0
              ? classifyApiSourceType(c0.source_type, c0)
              : classifyApiSourceType(c.srcType, null)
            const srcDisplay = brand ? CONFLICT_SRC_MODAL[brand] : { label: 'AI Knowledge', color: '#A78BFA', type: 'ai' }
            return (
              <div
                key={i}
                role="button"
                tabIndex={0}
                onClick={() => {
                  setSelected(i)
                  console.log('[Conflict Selection]', {
                    qid: c?.qid ?? null,
                    selectedValue: String(c?.answer ?? '').trim() || null,
                    trigger: 'click',
                  })
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setSelected(i)
                    console.log('[Conflict Selection]', {
                      qid: c?.qid ?? null,
                      selectedValue: String(c?.answer ?? '').trim() || null,
                      trigger: 'keyboard',
                    })
                  }
                }}
                style={{
                  display: 'flex', gap: 16, padding: 16, borderRadius: 12, cursor: 'pointer',
                  border: isSelected ? '2px solid var(--accent)' : '1px solid var(--border)',
                  background: isSelected ? 'rgba(37,99,235,.03)' : 'var(--bg)',
                  boxShadow: isSelected ? '0 0 0 3px rgba(37,99,235,.08)' : 'none',
                  transition: 'all .15s',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 56, paddingTop: 2 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: `${srcDisplay.color}10`, border: `1px solid ${srcDisplay.color}20`,
                  }}>
                    <SourceIcon type={srcDisplay.type} size={22} />
                  </div>
                  <span style={{ fontSize: 9, fontWeight: 700, color: srcDisplay.color, textTransform: 'uppercase', letterSpacing: '.3px', textAlign: 'center' }}>
                    {srcDisplay.label}
                  </span>
                  {c.conf > 0 && (
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 8,
                      color: c.conf >= 60 ? '#0891B2' : c.conf >= 40 ? '#D97706' : '#DC2626',
                      background: c.conf >= 60 ? 'rgba(8,145,178,.08)' : c.conf >= 40 ? 'rgba(217,119,6,.08)' : 'rgba(220,38,38,.08)',
                    }}>
                      {c.conf}%
                    </span>
                  )}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.08em', color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                    {conflictOptionHeading(c, i, { omitQid: true })}
                  </div>
                  {answerLines.length <= 1 ? (
                    <div style={{ fontSize: 12.5, color: 'var(--text1)', lineHeight: 1.7 }}>
                      {answerLines[0] || ''}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {answerLines.map((line, li) => (
                        <div key={`${i}-${li}`} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                          <span aria-hidden style={{ fontSize: 12, lineHeight: 1.45, color: 'var(--text2)' }}>•</span>
                          <span style={{ fontSize: 12.5, color: 'var(--text1)', lineHeight: 1.55 }}>
                            {line}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {Array.isArray(c.citations) && c.citations.length > 0 && (
                    <div style={{ marginTop: 12 }} onClick={e => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          toggleCitationsPanel(i)
                        }}
                        aria-expanded={citationPanelsOpen.has(i)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '7px 12px',
                          borderRadius: 8,
                          border: '1px solid var(--border)',
                          background: 'var(--bg2)',
                          fontSize: 10,
                          fontWeight: 700,
                          color: 'var(--text2)',
                          cursor: 'pointer',
                          fontFamily: 'var(--font)',
                          width: '100%',
                          maxWidth: 320,
                          justifyContent: 'flex-start',
                          textAlign: 'left',
                        }}
                      >
                        <span
                          aria-hidden
                          style={{
                            display: 'inline-flex',
                            width: 14,
                            justifyContent: 'center',
                            transform: citationPanelsOpen.has(i) ? 'rotate(90deg)' : 'rotate(0deg)',
                            transition: 'transform .15s ease',
                            color: 'var(--text3)',
                            flexShrink: 0,
                          }}
                        >
                          ▸
                        </span>
                        <span>
                          {citationPanelsOpen.has(i)
                            ? 'Hide source excerpts'
                            : `Show source excerpts (${c.citations.length})`}
                        </span>
                      </button>
                      {citationPanelsOpen.has(i) && (
                        <div
                          style={{
                            marginTop: 10,
                            paddingTop: 12,
                            borderTop: '1px solid var(--border)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 10,
                          }}
                        >
                          {c.citations.map((cit, ci) => (
                            <CitationBlock key={ci} citation={cit} index={ci} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div style={{
                  width: 22, height: 22, borderRadius: '50%', flexShrink: 0, marginTop: 2,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  border: isSelected ? '2px solid var(--accent)' : '2px solid var(--border)',
                  background: isSelected ? 'var(--accent)' : 'var(--bg2)',
                  transition: 'all .15s',
                }}>
                  {isSelected && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>}
                </div>
              </div>
            )
          })}
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, flexWrap: 'wrap', padding: '14px 24px',
          borderTop: '1px solid var(--border)', background: 'var(--bg3)',
          borderRadius: '0 0 16px 16px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <ModalBtn
              primary
              disabled={selected === null}
              onClick={() => {
                if (selected !== null && displayedConflicts[selected]) {
                  onConfirm(displayedConflicts[selected])
                }
              }}
            >
              Use selected response
            </ModalBtn>
            <ModalBtn ghost onClick={onClose}>Cancel</ModalBtn>
            {showNavArrows ? (
              <div
                role="group"
                aria-label={useInternalOptionNav ? 'Switch between competing responses' : 'Previous or next conflict question'}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  paddingLeft: 10, marginLeft: 2, borderLeft: '1px solid var(--border)',
                }}
              >
                <button
                  type="button"
                  onClick={prevHandler || undefined}
                  disabled={prevNavDisabled}
                  aria-label={prevAria}
                  title={prevAria}
                  style={{
                    width: 34, height: 34, borderRadius: 8,
                    border: '1px solid var(--border)', background: 'var(--bg2)',
                    color: 'var(--text1)', cursor: !prevNavDisabled ? 'pointer' : 'not-allowed',
                    opacity: !prevNavDisabled ? 1 : 0.45,
                    fontSize: 15, lineHeight: 1,
                  }}
                >
                  ←
                </button>
                <button
                  type="button"
                  onClick={nextHandler || undefined}
                  disabled={nextNavDisabled}
                  aria-label={nextAria}
                  title={nextAria}
                  style={{
                    width: 34, height: 34, borderRadius: 8,
                    border: '1px solid var(--border)', background: 'var(--bg2)',
                    color: 'var(--text1)', cursor: !nextNavDisabled ? 'pointer' : 'not-allowed',
                    opacity: !nextNavDisabled ? 1 : 0.45,
                    fontSize: 15, lineHeight: 1,
                  }}
                >
                  →
                </button>
              </div>
            ) : null}
          </div>
          {selected !== null ? (
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)', textAlign: 'right', flexShrink: 0 }}>
              Response {String.fromCharCode(65 + selected)} selected
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
