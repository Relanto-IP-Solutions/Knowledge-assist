/**
 * Maps GET /opportunities/{id}/answers rows (see sample response) into the review-question
 * shape used by Submit selections + opportunityReviewMeta.
 */

import {
  getPiclistAnswerRowsForQuestion,
  matchPiclistValueToAnswerId,
} from '../config/piclistOptionsByQid'
import { inferConflictGroupId } from './enrichAnswerIds'

/**
 * Parses multi-select values returned as Python-ish or JSON list strings, e.g.
 * "['REST', 'GraphQL']" or '["REST","GraphQL"]'.
 * @param {unknown} raw
 * @returns {string[]}
 */
/** Serialize selected values for multi-select answers (Python-style list string). */
export function serializeAssistMultiValue(values) {
  if (!values?.length) return ''
  /**
   * Backend wants a JSON-like list string for overrides, e.g. `["REST", "SOAP"]`.
   * Use JSON.stringify for safe escaping and stable quoting.
   */
  return `[${values.map(v => JSON.stringify(String(v))).join(', ')}]`
}

/**
 * @param {unknown} raw
 * @param {number} [depth] - unwrap nested list strings like `['[\'a\',\'b\']']` (see oid0009 QID-004)
 */
export function parseSerializedListAnswerValue(raw, depth = 0) {
  if (raw == null || raw === '') return []
  if (Array.isArray(raw)) {
    return raw.map(x => String(x).trim()).filter(Boolean)
  }
  const s = String(raw).trim()
  if (!s || !s.startsWith('[')) return []

  if (s.includes('"')) {
    try {
      const j = JSON.parse(s)
      if (Array.isArray(j)) {
        const arr = j.map(x => String(x).trim()).filter(Boolean)
        if (depth < 5 && arr.length === 1) {
          const inner = String(arr[0]).trim()
          if (inner.startsWith('[')) {
            const nested = parseSerializedListAnswerValue(inner, depth + 1)
            if (nested.length > 1 || (nested.length === 1 && nested[0] !== arr[0])) return nested
          }
        }
        return arr
      }
    } catch {
      /* fall through */
    }
  }

  const re = /'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)"/g
  const out = []
  let m
  while ((m = re.exec(s)) !== null) {
    const token = (m[1] ?? m[2] ?? '').replace(/\\(.)/g, '$1')
    if (token) out.push(token)
  }
  if (depth < 5 && out.length === 1) {
    const only = String(out[0]).trim()
    if (only.startsWith('[') && only.includes(']')) {
      const nested = parseSerializedListAnswerValue(only, depth + 1)
      if (nested.length > 1 || (nested.length === 1 && nested[0] !== out[0])) return nested
    }
  }
  return out
}

function normAnswerType(row) {
  return String(row?.answer_type ?? row?.answerType ?? '')
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
}

/** Match `opportunityReviewMeta` ROW_OPTION_KEYS — option arrays on merged GET /answers rows. */
const ROW_OPTION_KEYS = [
  'answers',
  'answer_list',
  'answerList',
  'possible_answers',
  'possibleAnswers',
  'answer_options',
  'answerOptions',
  'options',
]

/** First non-empty option list merged from GET /questions (UUID-backed). */
function firstOptionArrayFromRow(row) {
  if (!row || typeof row !== 'object') return null
  for (const k of ROW_OPTION_KEYS) {
    const v = row[k]
    if (Array.isArray(v) && v.length > 0) return v
  }
  return null
}

function looksLikeUuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(s || '').trim(),
  )
}

/** Ids known for this question: static piclist + structured option rows on the answer (e.g. GET /questions merge). */
function collectKnownAnswerIdsForMultiSelect(questionId, row) {
  const ids = new Set()
  for (const r of getPiclistAnswerRowsForQuestion(questionId)) {
    const id = r?.answer_id
    if (id != null && String(id).trim()) ids.add(String(id).trim())
  }
  for (const key of ROW_OPTION_KEYS) {
    const arr = row?.[key]
    if (!Array.isArray(arr)) continue
    for (const a of arr) {
      if (a != null && typeof a === 'object' && !Array.isArray(a)) {
        const id = a.answer_id ?? a.id ?? a.answerId
        if (id != null && String(id).trim()) ids.add(String(id).trim())
      }
    }
  }
  return ids
}

/** First non-empty option list on a merged GET /answers row (GET /questions UUIDs, not studio piclist). */
function firstNonEmptyRowOptionArray(row) {
  for (const k of ROW_OPTION_KEYS) {
    const v = row?.[k]
    if (Array.isArray(v) && v.length > 0) return v
  }
  return null
}

/** Normalize catalog / API objects to `{ answer_id, answer_value }` for `reviewQuestions.answers`. */
function mapMergedOptionsToAnswerRows(arr) {
  return arr
    .map(o => {
      if (o == null) return null
      if (typeof o === 'string' || typeof o === 'number' || typeof o === 'boolean') {
        const text = String(o).trim()
        if (!text) return null
        return { answer_id: text, answer_value: text }
      }
      if (typeof o === 'object' && !Array.isArray(o)) {
        const rawId = o.answer_id ?? o.id ?? o.answerId ?? o.option_id ?? o.optionId
        const text =
          o.answer_value ?? o.value ?? o.text ?? o.label ?? o.title ?? o.option_value ?? ''
        const idStr = rawId != null && String(rawId).trim() !== '' ? String(rawId).trim() : ''
        const tStr = String(text).trim()
        if (!idStr && !tStr) return null
        return { answer_id: idStr || tStr, answer_value: tStr || idStr }
      }
      return null
    })
    .filter(Boolean)
}

/**
 * @param {Record<string, unknown>} row - normalized opportunity answer row (+ type fields)
 * @param {{ questionText?: string, opportunityId?: string }} [opts] - pass `opportunityId` so rows with `conflicts[]` but no API `conflict_id` still get a stable group id for POST
 */
export function opportunityAnswerRowToReviewQuestion(row, opts = {}) {
  const questionId = String(row.question_id ?? '')
  const questionText = opts.questionText ?? row.question_text ?? row.questionText ?? questionId
  const at = normAnswerType(row)
  let requirementType = row.requirement_type ?? row.requirementType ?? ''
  if (!requirementType && (row.is_required === true || row.required === true)) requirementType = 'required'

  /** @type {Record<string, unknown>} */
  const out = {
    question_id: questionId,
    question_text: questionText,
    answer_type: row.answer_type ?? row.answerType ?? at,
    requirement_type: requirementType,
    final_answer_id: null,
    answers: [],
  }

  const finalizeNormalized = () => {
    // FALLBACK: ensure answer_value is never lost
    if (
      (!out.answers || out.answers.length === 0) &&
      row.answer_value != null &&
      String(row.answer_value).trim() !== ''
    ) {
      const t = String(row.answer_value).trim()

      out.answers = [
        {
          answer_id:
            row.answer_id != null && String(row.answer_id).trim() !== ''
              ? String(row.answer_id).trim()
              : t,
          answer_value: t,
        },
      ]

      out.final_answer_id =
        row.answer_id != null && String(row.answer_id).trim() !== ''
          ? String(row.answer_id).trim()
          : t
    }
    console.log('FINAL NORMALIZED:', out)
    return out
  }

  const conflictIdFromRow =
    row.conflict_id != null && String(row.conflict_id).trim() !== '' ? String(row.conflict_id).trim() : null
  const conflicts = Array.isArray(row.conflicts) ? row.conflicts : []
  const oppIdForInfer =
    opts.opportunityId != null && String(opts.opportunityId).trim() !== ''
      ? String(opts.opportunityId).trim()
      : ''
  const effectiveConflictId =
    conflicts.length > 0
      ? conflictIdFromRow || (oppIdForInfer ? inferConflictGroupId(oppIdForInfer, questionId) : null)
      : null

  if (conflicts.length > 0 && effectiveConflictId) {
    out.conflict = { conflict_id: effectiveConflictId }
    const primaryText = (() => {
      const v = row.answer_value
      if (v == null) return ''
      if (Array.isArray(v)) return v.map(x => String(x).trim()).filter(Boolean).join(', ')
      return String(v).trim()
    })()
    const primaryId =
      row.answer_id != null && String(row.answer_id).trim() !== ''
        ? String(row.answer_id)
        : primaryText || null

    const rows = []
    if (primaryText && primaryId) {
      rows.push({ answer_id: primaryId, answer_value: primaryText })
    }
    conflicts.forEach((c, i) => {
      const id = c?.answer_id != null ? String(c.answer_id) : String(i)
      const text = c?.answer_value != null ? String(c.answer_value) : ''
      if (!String(text).trim()) return
      rows.push({ answer_id: id, answer_value: text })
    })
    out.answers = rows
    if (primaryId) out.final_answer_id = primaryId
    return finalizeNormalized()
  }

  if (at === 'multi_select') {
    let list = []
    if (Array.isArray(row.selected_answer_ids) && row.selected_answer_ids.length) {
      list = row.selected_answer_ids.map(x => String(x).trim()).filter(Boolean)
    } else {
      list = parseSerializedListAnswerValue(row.answer_value)
      if (
        list.length === 0 &&
        row.answer_value != null &&
        String(row.answer_value).trim() !== '' &&
        !String(row.answer_value).trim().startsWith('[')
      ) {
        list = [String(row.answer_value).trim()]
      }
    }
    const rowOpts = firstNonEmptyRowOptionArray(row)
    const mappedFromApi = rowOpts ? mapMergedOptionsToAnswerRows(rowOpts) : []
    const catalog = getPiclistAnswerRowsForQuestion(questionId)
    if (mappedFromApi.length > 0) {
      out.answers = mappedFromApi
      const known = collectKnownAnswerIdsForMultiSelect(questionId, row)
      out.selected_answer_ids = list
        .map(val => {
          const v = String(val).trim()
          if (!v) return null
          if (looksLikeUuid(v)) return v
          if (known.has(v)) return v
          const mapped = matchPiclistValueToAnswerId(questionId, v)
          if (mapped) return String(mapped).trim()
          return null
        })
        .filter(Boolean)
      return out
    }
    if (catalog.length > 0) {
      out.answers = catalog
      const known = collectKnownAnswerIdsForMultiSelect(questionId, row)
      out.selected_answer_ids = list
        .map(val => {
          const v = String(val).trim()
          if (!v) return null
          if (known.has(v)) return v
          const mapped = matchPiclistValueToAnswerId(questionId, v)
          if (mapped) return String(mapped).trim()
          if (looksLikeUuid(v)) return v
          return null
        })
        .filter(Boolean)
      return finalizeNormalized()
    }
    out.answers = list.map(v => ({ answer_id: v, answer_value: v }))
    if (list.length) out.selected_answer_ids = list
    return finalizeNormalized()
  }

  if (at === 'picklist') {
    const rowOpts = firstNonEmptyRowOptionArray(row)
    const mappedFromApi = rowOpts ? mapMergedOptionsToAnswerRows(rowOpts) : []
    const catalog = getPiclistAnswerRowsForQuestion(questionId)
    const v = row.answer_value
    if (mappedFromApi.length > 0) {
      out.answers = mappedFromApi
      if (v != null && String(v).trim() !== '') {
        const t = String(v).trim()
        if (row.answer_id != null && String(row.answer_id).trim() !== '') {
          out.final_answer_id = String(row.answer_id).trim()
        } else {
          const matched = matchPiclistValueToAnswerId(questionId, t)
          if (matched) out.final_answer_id = matched
        }
      }
      return out
    }
    if (catalog.length > 0) {
      out.answers = catalog
      if (v != null && String(v).trim() !== '') {
        const t = String(v).trim()
        if (row.answer_id != null && String(row.answer_id).trim() !== '') {
          out.final_answer_id = String(row.answer_id).trim()
        } else {
          const matched = matchPiclistValueToAnswerId(questionId, t)
          if (matched) out.final_answer_id = matched
        }
      }
      return finalizeNormalized()
    }
    if (v != null && String(v).trim() !== '') {
      const t = String(v).trim()
      const id =
        row.answer_id != null && String(row.answer_id).trim() !== ''
          ? String(row.answer_id).trim()
          : matchPiclistValueToAnswerId(questionId, t) ?? t
      out.answers = [{ answer_id: id, answer_value: t }]
      out.final_answer_id = id
    }
    return finalizeNormalized()
  }

  if (row.answer_value != null && String(row.answer_value).trim() !== '') {
    const t = String(row.answer_value).trim()
    const id =
      row.answer_id != null && String(row.answer_id).trim() !== ''
        ? String(row.answer_id).trim()
        : matchPiclistValueToAnswerId(questionId, t) ?? t
    out.answers = [{ answer_id: id, answer_value: t }]
    out.final_answer_id = id
  }
  return finalizeNormalized()
}
