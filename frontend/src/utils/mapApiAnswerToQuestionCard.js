/**
 * Maps GET /opportunities/{id}/answers rows into the `q` shape expected by QuestionCard.
 */

import { finalizeCitationsForDisplay } from '../services/opportunityAnswersApi'
import { inferSourceTypeFromCitationFields } from './citationSourceInference'
import { serializeAssistMultiValue } from './opportunityAnswerRowToReviewQuestion'

function toConfidencePct(score) {
  if (score == null || Number.isNaN(score)) return 0
  return score <= 1 ? Math.round(score * 100) : Math.round(score)
}

function looksLikeUuid(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(value ?? '').trim(),
  )
}

function resolveAnswerLabelFromRows(answerRows, answerIdOrValue) {
  const needle = String(answerIdOrValue ?? '').trim()
  if (!needle || !Array.isArray(answerRows)) return ''
  const lowerNeedle = needle.toLowerCase()
  const hit = answerRows.find((row) => {
    if (!row || typeof row !== 'object') return false
    const id = String(row.answer_id ?? row.id ?? '').trim()
    const value = String(row.answer_value ?? row.value ?? row.text ?? row.label ?? '').trim()
    return id === needle || value === needle || value.toLowerCase() === lowerNeedle
  })
  if (!hit) return ''
  return String(hit.answer_value ?? hit.value ?? hit.text ?? hit.label ?? '').trim()
}

function firstSrcType(citations) {
  const c0 = citations?.[0]
  if (!c0) return 'unknown'
  const ch = classifyApiSourceType(c0.source_type, c0)
  if (ch) return ch
  return String(c0.source_type ?? 'unknown')
}

function isDocxLikeSource(stRaw, citation) {
  const st = String(stRaw ?? 'unknown').toLowerCase()
  const file = String((citation && (citation.source_file ?? citation.source_file_name)) ?? '').toLowerCase()
  const sname = String((citation && citation.source_name) ?? '').toLowerCase()
  if (file.endsWith('.docx') || sname.endsWith('.docx')) return true
  if (
    st.includes('docx') ||
    st.includes('wordprocessingml') ||
    st.includes('msword') ||
    st === 'word' ||
    st.includes('officedocument.wordprocessingml')
  )
    return true
  return false
}

/** Maps API citation source_type strings (and optional citation fields) to UI channel keys. */
export function classifyApiSourceType(stRaw, citation) {
  const effective = citation
    ? inferSourceTypeFromCitationFields({
        source_type: stRaw,
        source_file: citation.source_file ?? citation.source_file_name,
        source_name: citation.source_name ?? citation.source_document,
      })
    : stRaw
  if (isDocxLikeSource(effective, citation)) return 'gdrive'
  const st = String(effective ?? 'unknown').toLowerCase()
  if (st.includes('zoom')) return 'zoom'
  if (st.includes('slack')) return 'slack'
  if (st.includes('gmail') || st.includes('google_mail') || st === 'email' || st.includes('mail_message')) return 'gmail'
  if (st.includes('gdrive') || st.includes('google_drive') || st.includes('drive_doc') || (st.includes('drive') && !st.includes('slack'))) return 'gdrive'
  return null
}

/** Right-hand data source line on assist “AI recommended” header (Drive when excerpts are DOCX). */
export function assistDataSourceBrand(citations) {
  const fallback = { type: 'ai', label: 'AI INTELLIGENCE', color: 'rgba(27,38,79,.5)', showIcon: false }
  if (!citations?.length) return fallback
  const anyDrive = citations.some(c => classifyApiSourceType(c.source_type, c) === 'gdrive')
  if (anyDrive) {
    return { type: 'gdrive', label: 'GOOGLE DRIVE', color: '#34A853', showIcon: true }
  }
  const ch = classifyApiSourceType(citations[0].source_type, citations[0]) ?? 'ai'
  const meta = {
    zoom: { type: 'zoom', label: 'ZOOM', color: '#2D8CFF', showIcon: true },
    gdrive: { type: 'gdrive', label: 'GOOGLE DRIVE', color: '#34A853', showIcon: true },
    gmail: { type: 'gmail', label: 'GMAIL', color: '#EA4335', showIcon: true },
    slack: { type: 'slack', label: 'SLACK', color: '#E01E5A', showIcon: true },
    ai: fallback,
  }
  return meta[ch] || fallback
}

const CHANNEL_ORDER = ['zoom', 'gdrive', 'gmail', 'slack', 'ai']

const CHANNEL_META = {
  zoom: { name: 'Zoom', color: '#2D8CFF', type: 'zoom' },
  gdrive: { name: 'Google Drive', color: '#34A853', type: 'gdrive' },
  gmail: { name: 'Gmail', color: '#EA4335', type: 'gmail' },
  slack: { name: 'Slack', color: '#E01E5A', type: 'slack' },
  ai: { name: 'AI Intelligence', color: '#7C3AED', type: 'ai' },
}

/** One chip per channel for QuestionCard header (matches mock `q.srcs` shape). */
function citationsToUniqueChannelSrcs(citations) {
  if (!citations?.length) return []
  const seen = new Set()
  const picked = new Map()
  for (const c of citations) {
    const ch = classifyApiSourceType(c.source_type, c) || 'ai'
    if (seen.has(ch)) continue
    seen.add(ch)
    const m = CHANNEL_META[ch] || CHANNEL_META.ai
    picked.set(ch, { name: m.name, color: m.color, type: m.type, minimal: true })
  }
  const ordered = CHANNEL_ORDER.filter(ch => picked.has(ch)).map(ch => picked.get(ch))
  return ordered.length ? ordered : []
}

/** Backend sometimes sends this when no AI extraction — treat like empty for display. */
function isPlaceholderAnswerValue(s) {
  const t = String(s ?? '').trim()
  if (!t) return true
  const n = t.toLowerCase().replace(/\s+/g, ' ').replace(/[!?.,;:]+$/g, '')
  if (n === 'no extracted answer available for this question') return true
  if (n === 'no extracted answer available in payload for this question') return true
  if (n === 'user') return true
  if (n === 'no answer generated') return true
  if (n === 'new answer generated') return true
  if (n === 'no new answer generated') return true
  if (n === 'nothing') return true
  if (n === 'null') return true
  return false
}

/** Primary answer text for conflict UI (normalized row or raw API with array answer_value). */
function primaryAnswerDisplay(row) {
  const v = row.answer_value
  if (v == null) return ''
  if (Array.isArray(v)) {
    const parts = v.map(x => String(x).trim()).filter(Boolean)
    return parts.length ? serializeAssistMultiValue(parts) : ''
  }
  return String(v).trim()
}

/** Build QuestionCard `conflicts`: selectable options { answer, conf, srcType, qid, role } */
function buildConflictsForCard(row) {
  const citations = row.citations || []
  const list = Array.isArray(row.conflicts) ? row.conflicts : []
  const answerRows = Array.isArray(row.answers) ? row.answers : []
  const resolveConflictDisplayAnswer = (conflict, fallbackText) => {
    const rawAnswer = String(conflict?.answer_value ?? conflict?.answer ?? conflict?.value ?? '').trim()
    if (!rawAnswer) return String(fallbackText ?? '').trim()
    // If backend sent UUID text instead of label, recover label from answer rows using answer_id/value.
    if (looksLikeUuid(rawAnswer)) {
      const fromId = resolveAnswerLabelFromRows(answerRows, conflict?.answer_id ?? rawAnswer)
      if (fromId && !looksLikeUuid(fromId)) return fromId
    }
    const byAnswerId = resolveAnswerLabelFromRows(answerRows, conflict?.answer_id)
    if (byAnswerId && !looksLikeUuid(byAnswerId) && looksLikeUuid(rawAnswer)) return byAnswerId
    return rawAnswer
  }
  const validConflicts = list.filter(c => {
    const ans = resolveConflictDisplayAnswer(c, '')
    return ans && !isPlaceholderAnswerValue(ans)
  })
  const qid = String(row.question_id ?? '')
  const primary = primaryAnswerDisplay(row)
  const hasValidPrimary = Boolean(primary && !isPlaceholderAnswerValue(primary))

  /**
   * Conflict Handling – Valid to Null Case:
   * if backend keeps previous valid answer but new conflict candidates are empty/placeholder,
   * do not classify as a conflict.
   */
  if (validConflicts.length === 0 && hasValidPrimary) return []

  if (validConflicts.length >= 2) {
    const out = []
    if (primary) {
      const pid =
        row.answer_id != null && String(row.answer_id).trim() !== ''
          ? String(row.answer_id)
          : null
      out.push({
        answer: primary,
        answer_id: pid,
        conf: toConfidencePct(row.confidence_score),
        srcType: firstSrcType(citations),
        qid,
        role: 'primary',
        citations: Array.isArray(citations) && citations.length ? citations : [],
      })
    }
    validConflicts.forEach((c, i) => {
      const ans = resolveConflictDisplayAnswer(c, '')
      const cid = c?.answer_id != null && String(c.answer_id).trim() !== '' ? String(c.answer_id) : null
      const ccits = Array.isArray(c.citations) ? c.citations : []
      out.push({
        // If backend omitted text, still show a selectable entry so FE reflects "conflict exists".
        answer: ans || `Conflict option ${i + 1}`,
        answer_id: cid,
        conf: toConfidencePct(c.confidence_score),
        srcType: firstSrcType(ccits),
        qid,
        role: 'conflict',
        conflictIndex: i + 1,
        citations: ccits,
      })
    })
    const seen = new Set()
    return out.filter((item) => {
      const key = String(item.answer_id ?? item.answer).trim()
      if (!key) return false
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }
  if (validConflicts.length === 1) {
    const alt = resolveConflictDisplayAnswer(validConflicts[0], '')
    const pid =
      row.answer_id != null && String(row.answer_id).trim() !== '' ? String(row.answer_id) : null
    const cid =
      validConflicts[0]?.answer_id != null && String(validConflicts[0].answer_id).trim() !== ''
        ? String(validConflicts[0].answer_id)
        : null
    const altCits = Array.isArray(validConflicts[0].citations) ? validConflicts[0].citations : []
    const a = {
      answer: primary || alt,
      answer_id: pid,
      conf: toConfidencePct(row.confidence_score),
      srcType: firstSrcType(citations),
      qid,
      role: 'primary',
      citations: Array.isArray(citations) && citations.length ? citations : [],
    }
    const b = {
      answer: alt || primary || 'Conflict option 1',
      answer_id: cid,
      conf: toConfidencePct(list[0].confidence_score),
      srcType: firstSrcType(altCits),
      qid,
      role: 'conflict',
      conflictIndex: 1,
      citations: altCits,
    }
    if (String(a.answer).trim() === String(b.answer).trim()) return []
    return [a, b]
  }
  return []
}

/**
 * True when Clarify Conflict / dual-response UI should apply.
 */
export function apiAnswerNeedsConflictClarify(row) {
  return buildConflictsForCard(row).length >= 2
}

/**
 * @param {import('../services/opportunityAnswersApi').OpportunityAnswerRow} row
 * @param {string} [questionText]
 */
export function buildQuestionCardModelFromApiAnswer(row, questionText) {
  const citations = finalizeCitationsForDisplay(row)
  const conflicts = buildConflictsForCard(row)
  const primaryRaw = primaryAnswerDisplay(row)
  const primaryAnswer =
    primaryRaw && !isPlaceholderAnswerValue(primaryRaw) ? primaryRaw : null
  const fallbackFromConflict = conflicts[0]?.answer != null ? String(conflicts[0].answer).trim() : ''
  const fb = fallbackFromConflict && !isPlaceholderAnswerValue(fallbackFromConflict) ? fallbackFromConflict : ''
  const answer = primaryAnswer ?? fb

  const conf = toConfidencePct(row.confidence_score)
  const headerSrcs = citationsToUniqueChannelSrcs(citations)

  return {
    id: row.question_id,
    text: (questionText && String(questionText).trim()) || String(row.question_id),
    answer,
    /** Keep primary answer id so UI can render selected option even if answer_value is null. */
    answer_id:
      row?.answer_id != null && String(row.answer_id).trim() !== ''
        ? String(row.answer_id).trim()
        : null,
    /** Preserve the payload answer_value so structured UI can highlight the right option(s). */
    answer_value: primaryRaw || null,
    /** Used for post-submit AI/Human filters + display cues. */
    is_user_override: row?.is_user_override ?? null,
    conf,
    p: conf >= 60 ? 'P1' : conf >= 40 ? 'P2' : 'P0',
    pc: conf >= 60 ? '#D97706' : conf >= 40 ? '#475569' : '#DC2626',
    /** Branded channel chips (Zoom, Slack, …) derived from GET /answers citations. */
    srcs: headerSrcs,
    conflicts,
    citations,
    fromApi: true,
    apiConfidencePct: conf,
    /** picklist | multi-select | … from GET /answers (assist Review UI) */
    apiAnswerType: row.answer_type != null ? String(row.answer_type) : null,
    apiRequirementType: row.requirement_type != null ? String(row.requirement_type) : null,
  }
}
