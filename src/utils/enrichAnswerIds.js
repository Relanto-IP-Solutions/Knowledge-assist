/**
 * Fills `answer_id` / `conflict_id` when GET /answers (or static exports) omit them
 * but include `answer_value` and `conflicts[]` — e.g. oid0009_responses_form_output JSON.
 *
 * For live Swagger/API rows, use `skipPiclistInference` so ids stay backend UUIDs from GET /questions
 * and POST /answers does not receive studio numeric ids from piclistStudioRows.json.
 */

import { matchPiclistValueToAnswerId } from '../config/piclistOptionsByQid'

function looksLikeUuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(s || '').trim(),
  )
}

/** @param {string} qid */
export function inferPrimaryAnswerId(qid, rawScalar) {
  if (rawScalar == null) return null
  const t = String(rawScalar).trim()
  if (!t) return null
  if (looksLikeUuid(t)) return t
  return matchPiclistValueToAnswerId(qid, t) ?? t
}

/**
 * @param {string} qid
 * @param {string} [opportunityId]
 * @param {number} index
 * @param {string} answerValueText
 */
export function inferConflictAnswerId(qid, opportunityId, index, answerValueText, opts = {}) {
  const t = String(answerValueText ?? '').trim()
  if (!t) return null
  if (looksLikeUuid(t)) return t
  if (!opts.skipPiclistInference) {
    const fromCatalog = matchPiclistValueToAnswerId(qid, t)
    if (fromCatalog) return fromCatalog
  }
  const prefix = opportunityId ? `${String(opportunityId)}:` : ''
  return `${prefix}${qid}:conflict:${index + 1}`
}

/** @param {string} opportunityId @param {string} qid */
export function inferConflictGroupId(opportunityId, qid) {
  if (!opportunityId || !qid) return null
  return `${String(opportunityId)}:${String(qid)}:conflict`
}

/** @param {string} qid @param {unknown[]} rawArray @param {{ skipPiclistInference?: boolean }} [opts] */
export function inferSelectedAnswerIdsFromMultiRaw(qid, rawArray, opts = {}) {
  if (!Array.isArray(rawArray) || !rawArray.length) return undefined
  const skip = opts.skipPiclistInference === true
  const ids = rawArray
    .map(v => {
      const s = String(v).trim()
      if (!s) return null
      if (skip) return s
      return matchPiclistValueToAnswerId(qid, s) ?? s
    })
    .filter(Boolean)
  return ids.length ? ids : undefined
}

/**
 * @param {Record<string, unknown>} rawRow - original API/export row (before value coercion)
 * @param {{
 *   question_id: string,
 *   answer_id: string | null,
 *   answer_value: string | null,
 *   conflict_id: string | null,
 *   conflicts: Array<{ answer_id: string | null, answer_value: string, confidence_score: number, citations: unknown[] }>,
 *   [k: string]: unknown,
 * }} normalized - output of field normalization (citations, etc.)
 * @param {string} [opportunityId]
 * @param {{ skipPiclistInference?: boolean }} [opts] - when true (live GET /answers), do not inject studio ids from piclist JSON
 */
export function enrichAnswerRowAfterNormalize(normalized, rawRow, opportunityId, opts = {}) {
  const qid = normalized.question_id
  const rawVal = rawRow.answer_value
  const skipPic = opts.skipPiclistInference === true
  const inferOpts = { skipPiclistInference: skipPic }

  let answer_id = normalized.answer_id
  if (!answer_id && normalized.answer_value != null && !Array.isArray(rawVal) && !skipPic) {
    answer_id = inferPrimaryAnswerId(qid, rawVal) ?? inferPrimaryAnswerId(qid, normalized.answer_value)
  }

  let conflict_id = normalized.conflict_id
  const conflicts = normalized.conflicts
  if (!conflict_id && conflicts.length > 0 && opportunityId) {
    conflict_id = inferConflictGroupId(opportunityId, qid)
  }

  const enrichedConflicts = conflicts.map((c, i) => ({
    ...c,
    answer_id: c.answer_id ?? inferConflictAnswerId(qid, opportunityId, i, c.answer_value, inferOpts),
  }))

  const selected_answer_ids = Array.isArray(rawVal)
    ? inferSelectedAnswerIdsFromMultiRaw(qid, rawVal, inferOpts)
    : undefined

  return {
    ...normalized,
    answer_id,
    conflict_id,
    conflicts: enrichedConflicts,
    ...(selected_answer_ids ? { selected_answer_ids } : {}),
  }
}

/**
 * Enrich a full `{ opportunity_id, answers[] }` payload (e.g. for export or CLI).
 * @param {{ opportunity_id?: string, answers?: unknown[] }} data
 */
export function enrichAnswersResponsePayload(data) {
  const oid = data?.opportunity_id != null ? String(data.opportunity_id) : ''
  const answers = Array.isArray(data?.answers) ? data.answers : []
  return {
    ...data,
    opportunity_id: oid || data?.opportunity_id,
    answers: answers.map(raw => {
      const row = enrichRawAnswerExportRow(raw, oid)
      return row
    }),
  }
}

/**
 * Single raw export row → JSON-serializable object with answer_id on row + conflicts.
 * @param {Record<string, unknown>} raw
 * @param {string} opportunityId
 */
export function enrichRawAnswerExportRow(raw, opportunityId) {
  const qid = String(raw.question_id ?? '')
  const rawVal = raw.answer_value
  const citations = Array.isArray(raw.citations) ? raw.citations : []
  const rawConflicts = Array.isArray(raw.conflicts) ? raw.conflicts : []

  let answer_id =
    raw.answer_id != null && String(raw.answer_id).trim() !== '' ? String(raw.answer_id) : null
  if (!answer_id && rawVal != null && !Array.isArray(rawVal)) {
    answer_id = inferPrimaryAnswerId(qid, rawVal)
  }

  let conflict_id = raw.conflict_id ? String(raw.conflict_id) : null
  if (!conflict_id && rawConflicts.length > 0 && opportunityId) {
    conflict_id = inferConflictGroupId(opportunityId, qid)
  }

  const conflicts = rawConflicts.map((c, i) => {
    const entry = c && typeof c === 'object' ? c : {}
    const av = entry.answer_value != null ? String(entry.answer_value) : ''
    let aid = entry.answer_id != null && String(entry.answer_id).trim() !== '' ? String(entry.answer_id) : null
    if (!aid && av) aid = inferConflictAnswerId(qid, opportunityId, i, av)
    return {
      ...entry,
      answer_id: aid,
      answer_value: av,
      confidence_score: typeof entry.confidence_score === 'number' ? entry.confidence_score : 0,
      citations: Array.isArray(entry.citations) ? entry.citations : [],
    }
  })

  const out = {
    ...raw,
    question_id: qid,
    answer_id,
    answer_value: rawVal,
    confidence_score: typeof raw.confidence_score === 'number' ? raw.confidence_score : 0,
    citations,
    conflict_id,
    conflicts,
  }

  if (Array.isArray(rawVal) && rawVal.length) {
    const sids = inferSelectedAnswerIdsFromMultiRaw(qid, rawVal)
    if (sids) out.selected_answer_ids = sids
  }

  return out
}
