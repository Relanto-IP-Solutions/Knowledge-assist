import { useState } from 'react'
import {
  CITATION_BUCKET_ORDER,
  citationDisplayLabelFallback,
  citationSectionTitle,
  groupCitationsByBucket,
  inferSourceTypeFromCitationFields,
} from '../utils/citationSourceInference'

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'

function formatBody(text) {
  if (!text) return null
  const parts = text.split(/\n{2,}/).map(s => s.trim()).filter(Boolean)
  if (parts.length <= 1) {
    return text.split('\n').map((line, i) => (
      <p key={i} style={{ margin: i === 0 ? 0 : '0.65em 0 0', lineHeight: 1.55 }}>
        {line}
      </p>
    ))
  }
  return parts.map((block, i) => (
    <p key={i} style={{ margin: i === 0 ? 0 : '0.85em 0 0', lineHeight: 1.55 }}>
      {block.split('\n').map((line, j) => (
        <span key={j}>
          {j > 0 && <br />}
          {line}
        </span>
      ))}
    </p>
  ))
}

function normalizeCitationSourceType(input) {
  const c = input != null && typeof input === 'object' && 'source_type' in input ? input : { source_type: input }
  const merged = inferSourceTypeFromCitationFields({
    source_type: c.source_type,
    source_file: c.source_file ?? c.source_file_name,
    source_name: c.source_name ?? c.source_document,
  })
  const s = String(merged ?? 'unknown').toLowerCase()
  const file = String(c.source_file ?? c.source_file_name ?? '').toLowerCase()
  const sname = String(c.source_name ?? '').toLowerCase()
  if (
    file.endsWith('.docx') ||
    sname.endsWith('.docx') ||
    s.includes('docx') ||
    s.includes('wordprocessingml') ||
    s.includes('msword') ||
    s === 'word' ||
    s.includes('officedocument.wordprocessingml')
  )
    return 'gdrive'
  if (s.includes('zoom')) return 'zoom'
  if (s.includes('slack')) return 'slack'
  if (s.includes('gmail') || s.includes('google_mail') || s === 'email' || s.includes('mail_message')) return 'gmail'
  if (s.includes('gdrive') || s.includes('google_drive') || s.includes('drive_doc') || (s.includes('drive') && !s.includes('slack'))) return 'gdrive'
  return 'unknown'
}

function GmailMark({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
      <path d="M22 6.5v11c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2v-11l10 7.5L22 6.5z" fill="#4285F4" />
      <path d="M21.8 5.5L12 12.5 2.2 5.5C2.6 5.2 3.2 5 4 5h16c.8 0 1.4.2 1.8.5z" fill="#EA4335" />
      <path d="M2.2 5.5L12 12.5V5H4c-.8 0-1.4.2-1.8.5z" fill="#FBBC04" />
      <path d="M21.8 5.5L12 12.5V5h8c.8 0 1.4.2 1.8.5z" fill="#34A853" />
    </svg>
  )
}

function sourceTypeIcon(citationOrType) {
  const t = normalizeCitationSourceType(citationOrType)
  switch (t) {
    case 'zoom':
      return (
        <svg width="14" height="14" viewBox="0 0 48 48" fill="none" style={{ flexShrink: 0 }}>
          <circle cx="24" cy="24" r="24" fill="#4A8CFF"/>
          <rect x="10" y="15" width="19" height="14" rx="3.5" fill="#fff"/>
          <path d="M29 19.5L37 15v16l-8-4.5" fill="#fff"/>
        </svg>
      )
    case 'gdrive':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
          <path d="M4.4 20l4-7h11.2l-4 7z" fill="#4285F4"/>
          <path d="M15.6 13L11.6 6h8l4 7z" fill="#FBBC04"/>
          <path d="M4.4 20l4-7L11.6 6H3.6L0 13z" fill="#34A853"/>
        </svg>
      )
    case 'slack':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
          <path d="M5.1 15a1.5 1.5 0 1 1 0-3h3.8v3H5.1z" fill="#E01E5A"/>
          <path d="M9 5.1a1.5 1.5 0 1 1 3 0v3.8H9V5.1z" fill="#36C5F0"/>
          <path d="M18.9 9a1.5 1.5 0 1 1 0 3h-3.8V9h3.8z" fill="#2EB67D"/>
          <path d="M15 18.9a1.5 1.5 0 1 1-3 0v-3.8h3v3.8z" fill="#ECB22E"/>
        </svg>
      )
    case 'gmail':
      return <GmailMark size={14} />
    default:
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8B949E" strokeWidth="2" strokeLinecap="round" style={{ flexShrink: 0 }}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
      )
  }
}

function sourceTypeMeta(citationOrType) {
  const c = citationOrType != null && typeof citationOrType === 'object' ? citationOrType : null
  const file = String(c?.source_file ?? '').toLowerCase()
  const sname = String(c?.source_name ?? '').toLowerCase()
  const docx = file.endsWith('.docx') || sname.endsWith('.docx')
  const t = normalizeCitationSourceType(citationOrType)
  if (docx && t === 'gdrive') {
    return { label: 'Word · DOCX', color: '#2563EB', bg: 'rgba(37,99,235,.08)', border: 'rgba(37,99,235,.22)' }
  }
  switch (t) {
    case 'zoom': return { label: 'Zoom', color: '#2D8CFF', bg: 'rgba(45,140,255,.08)', border: 'rgba(45,140,255,.22)' }
    case 'gdrive': return { label: 'Google Drive', color: '#34A853', bg: 'rgba(52,168,83,.08)', border: 'rgba(52,168,83,.22)' }
    case 'gmail': return { label: 'Gmail', color: '#EA4335', bg: 'rgba(234,67,53,.08)', border: 'rgba(234,67,53,.22)' }
    case 'slack': return { label: 'Slack', color: '#E01E5A', bg: 'rgba(224,30,90,.08)', border: 'rgba(224,30,90,.22)' }
    default: {
      const label =
        c != null
          ? citationDisplayLabelFallback(c)
          : String(
              citationOrType != null && typeof citationOrType === 'object' && 'source_type' in citationOrType
                ? citationOrType.source_type
                : citationOrType ?? 'Evidence',
            )
      return { label, color: '#8B949E', bg: 'rgba(139,148,158,.08)', border: 'rgba(139,148,158,.22)' }
    }
  }
}

function confidenceColor(score) {
  const pct = score <= 1 ? score * 100 : score
  if (pct >= 80) return '#16A34A'
  if (pct >= 60) return '#0891B2'
  if (pct >= 40) return '#CA8A04'
  return '#DC2626'
}

function confidencePercent(score) {
  if (score == null) return null
  return score <= 1 ? Math.round(score * 100) : Math.round(score)
}

/** Renders a single citation with source icon, name, quote, and relevance (GET /answers fields). */
export function CitationBlock({ citation, index }) {
  const meta = sourceTypeMeta(citation)
  const relPct = citation.relevance_score != null
    ? (citation.relevance_score <= 1 ? Math.round(citation.relevance_score * 100) : Math.round(citation.relevance_score))
    : null

  const rawType = String(citation.source_type ?? '').trim()
  const filePath = citation.source_file != null ? String(citation.source_file).trim() : ''
  const showFilePath = filePath && filePath !== String(citation.source_name ?? '').trim()
  const metaBits = []
  if (citation.timestamp_str) metaBits.push(`Timestamp: ${citation.timestamp_str}`)
  if (citation.page_number != null && citation.page_number !== '') metaBits.push(`Page: ${citation.page_number}`)
  if (citation.chunk_id) metaBits.push(`chunk_id: ${citation.chunk_id}`)

  return (
    <div style={{
      borderRadius: 8,
      border: `1px solid ${meta.border}`,
      background: meta.bg,
      padding: '10px 12px',
      marginTop: index > 0 ? 8 : 0,
    }}>
      {/* Citation header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        {sourceTypeIcon(citation)}
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '.04em',
          color: meta.color, textTransform: 'uppercase',
        }}>
          {meta.label}
        </span>
        {citation.source_name && (
          <span style={{
            fontSize: 10, fontWeight: 600, color: 'var(--text2)',
            maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
            title={citation.source_name}
          >
            {citation.source_name}
          </span>
        )}
      </div>

      {rawType ? (
        <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', marginBottom: 6, fontFamily: 'ui-monospace, monospace' }}>
          source_type: {rawType}
        </div>
      ) : null}

      {showFilePath ? (
        <div style={{
          fontSize: 10, fontWeight: 500, color: 'var(--text2)', marginBottom: 8, lineHeight: 1.45,
          wordBreak: 'break-all',
        }} title={filePath}>
          <span style={{ fontWeight: 700, color: 'var(--text3)' }}>source_file: </span>
          {filePath}
        </div>
      ) : null}

      {metaBits.length > 0 ? (
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, lineHeight: 1.4 }}>
          {metaBits.join(' · ')}
        </div>
      ) : null}

      {/* Quote / excerpt lines (payload `quote`) */}
      {citation.quote && (
        <div style={{
          fontSize: 11, color: 'var(--text1)', lineHeight: 1.65,
          borderLeft: `3px solid ${meta.color}40`,
          paddingLeft: 10,
          fontStyle: 'italic',
          wordBreak: 'break-word',
        }}>
          "{citation.quote}"
        </div>
      )}

      {relPct != null && (
        <div style={{
          marginTop: citation.quote ? 10 : 8,
          fontSize: 10,
          fontWeight: 600,
          color: 'var(--text3)',
          letterSpacing: '0.02em',
        }}>
          Relevance score (payload <code style={{ fontSize: 9 }}>relevance_score</code>):{' '}
          <span style={{ color: confidenceColor(citation.relevance_score), fontWeight: 700 }}>{relPct}%</span>
        </div>
      )}
    </div>
  )
}

/**
 * Groups GET /answers citations into Zoom / DOCX / Slack / Drive / Gmail / Other with headings.
 * @param {{ citations: object[] }} props
 */
export function SourcesGroupedPanel({ citations }) {
  const groups = groupCitationsByBucket(citations)
  return (
    <div>
      {CITATION_BUCKET_ORDER.map(bucket => {
        const list = groups[bucket]
        if (!list.length) return null
        return (
          <div key={bucket} style={{ marginBottom: 22 }}>
            <div style={{
              fontSize: 10,
              fontWeight: 800,
              letterSpacing: '.1em',
              color: 'var(--text3)',
              textTransform: 'uppercase',
              marginBottom: 12,
              paddingBottom: 8,
              borderBottom: '1px solid rgba(15,23,42,.08)',
            }}>
              {citationSectionTitle(bucket)}
              <span style={{ fontWeight: 600, letterSpacing: '0.04em', marginLeft: 8, color: 'var(--text3)', opacity: 0.85 }}>
                ({list.length})
              </span>
            </div>
            {list.map((c, i) => (
              <CitationBlock key={String(c.chunk_id || `${bucket}-${i}`)} citation={c} index={i} />
            ))}
          </div>
        )
      })}
    </div>
  )
}

/** Renders a single conflict entry with answer, confidence, and its citations */
function ConflictBlock({ conflict, index, total }) {
  const [citationsOpen, setCitationsOpen] = useState(false)
  const confPct = confidencePercent(conflict.confidence_score)
  const hasCitations = conflict.citations && conflict.citations.length > 0
  const letter = String.fromCharCode(65 + index)

  return (
    <div style={{
      borderRadius: 10,
      border: '1px solid rgba(232,83,46,.20)',
      background: 'var(--bg)',
      overflow: 'hidden',
      marginTop: index > 0 ? 10 : 0,
    }}>
      {/* Conflict header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px',
        background: 'rgba(232,83,46,.04)',
        borderBottom: '1px solid rgba(232,83,46,.12)',
      }}>
        <span style={{
          width: 24, height: 24, borderRadius: 6,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 800, color: SI_ORANGE,
          background: 'rgba(232,83,46,.10)', border: '1px solid rgba(232,83,46,.25)',
          flexShrink: 0,
        }}>
          {letter}
        </span>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>
          Response {letter}
        </span>
        {confPct != null && (
          <span style={{
            marginLeft: 'auto',
            fontSize: 10, fontWeight: 700,
            padding: '3px 8px', borderRadius: 6,
            color: confidenceColor(conflict.confidence_score),
            background: `${confidenceColor(conflict.confidence_score)}10`,
            border: `1px solid ${confidenceColor(conflict.confidence_score)}30`,
          }}>
            {confPct}% confidence
          </span>
        )}
      </div>

      {/* Answer value */}
      <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text1)', lineHeight: 1.7, fontFamily: 'var(--font)' }}>
        {formatBody(conflict.answer_value)}
      </div>

      {/* Citations for this conflict (collapsed by default) */}
      {hasCitations && (
        <div style={{ padding: '0 14px 14px' }}>
          <button
            type="button"
            onClick={() => setCitationsOpen(o => !o)}
            aria-expanded={citationsOpen}
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
                transform: citationsOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                transition: 'transform .15s ease',
                color: 'var(--text3)',
                flexShrink: 0,
              }}
            >
              ▸
            </span>
            <span>
              {citationsOpen
                ? 'Hide source excerpts'
                : `Show source excerpts (${conflict.citations.length})`}
            </span>
          </button>
          {citationsOpen && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {conflict.citations.map((c, i) => (
                <CitationBlock key={c.chunk_id || i} citation={c} index={i} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


/** @param {{ answer: { question_id: string, answer_value: string|null, confidence_score: number, citations: object[], conflict_id: string|null, conflicts: object[] } }} props */
export function apiAnswerElementId(questionId) {
  return `api-ans-${String(questionId).replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

export function ApiAnswerCard({ answer }) {
  const hasConflicts = answer.conflicts && answer.conflicts.length > 0
  const hasCitations = answer.citations && answer.citations.length > 0
  const rawConf = answer.confidence_score
  const confPct = confidencePercent(rawConf)
  const eid = apiAnswerElementId(answer.question_id)

  return (
    <article
      id={eid}
      style={{
        borderRadius: 10,
        border: `1px solid ${hasConflicts ? 'rgba(232,83,46,.35)' : 'var(--border)'}`,
        background: 'var(--bg2)',
        marginBottom: 14,
        overflow: 'hidden',
        boxShadow: hasConflicts ? '0 0 0 1px rgba(232,83,46,.08)' : 'none',
      }}
    >
      {/* Header */}
      <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--border)', background: 'var(--bg3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 800,
            letterSpacing: '-0.02em',
            color: SI_NAVY,
            fontFamily: 'var(--font)',
            flex: 1,
          }}>
            {answer.question_id || '—'}
          </h3>
          {answer.conflict_id && (
            <span style={{
              fontSize: 9, fontWeight: 700,
              padding: '3px 8px', borderRadius: 6,
              background: 'rgba(232,83,46,.08)',
              border: '1px solid rgba(232,83,46,.22)',
              color: SI_ORANGE,
              fontFamily: 'monospace',
            }}>
              {answer.conflict_id}
            </span>
          )}
        </div>
        {confPct != null && (
          <div style={{ marginTop: 6, fontSize: 11, fontWeight: 600, color: 'var(--text3)' }}>
            Confidence:{' '}
            <span style={{ color: confidenceColor(rawConf) }}>
              {confPct}%
            </span>
          </div>
        )}
      </div>

      {/* Conflict alert banner */}
      {hasConflicts && (
        <div
          role="alert"
          style={{
            padding: '10px 14px',
            background: 'rgba(232,83,46,.06)',
            borderBottom: '1px solid rgba(232,83,46,.2)',
            fontSize: 12,
            fontWeight: 600,
            color: SI_ORANGE,
            fontFamily: 'var(--font)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={SI_ORANGE} strokeWidth="2.2" strokeLinecap="round" style={{ flexShrink: 0 }}>
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <span>
            Conflicting information detected — {answer.conflicts.length} conflicting response{answer.conflicts.length !== 1 ? 's' : ''}
          </span>
        </div>
      )}

      {/* Answer body (only shown when answer_value is not null) */}
      {answer.answer_value != null && (
        <div style={{ padding: '12px 14px 14px', fontSize: 12, color: 'var(--text1)', fontFamily: 'var(--font)' }}>
          {formatBody(answer.answer_value)}
        </div>
      )}

      {/* If answer_value is null and there are conflicts, show a note */}
      {answer.answer_value == null && hasConflicts && (
        <div style={{
          padding: '10px 14px',
          fontSize: 11,
          color: 'var(--text3)',
          fontStyle: 'italic',
          borderBottom: '1px solid var(--border)',
        }}>
          No single answer — review conflicting responses below to resolve.
        </div>
      )}

      {/* Top-level citations */}
      {hasCitations && (
        <div style={{ padding: '0 14px 14px' }}>
          <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.1em', color: 'var(--text3)', marginBottom: 8 }}>
            CITATIONS ({answer.citations.length})
          </div>
          {answer.citations.map((c, i) => (
            <CitationBlock key={c.chunk_id || i} citation={c} index={i} />
          ))}
        </div>
      )}

      {/* Conflict details */}
      {hasConflicts && (
        <div style={{ padding: '0 14px 14px' }}>
          <div style={{
            fontSize: 9, fontWeight: 800, letterSpacing: '.1em', color: SI_ORANGE, marginBottom: 10,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={SI_ORANGE} strokeWidth="2.5" strokeLinecap="round" style={{ flexShrink: 0 }}>
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            CONFLICTING RESPONSES
          </div>
          {answer.conflicts.map((conflict, i) => (
            <ConflictBlock key={i} conflict={conflict} index={i} total={answer.conflicts.length} />
          ))}
        </div>
      )}
    </article>
  )
}
