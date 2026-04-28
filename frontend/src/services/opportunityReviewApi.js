import { normalizeFeedbackTypeForWire } from '../utils/opportunityReviewMeta'
import { api, API_BASE } from './apiClient'

/** @param {string} responseText */
export function formatOpportunityReviewApiErrorBody(responseText) {
  const t = String(responseText ?? '').trim()
  if (!t) return ''
  try {
    const j = JSON.parse(t)
    if (typeof j.detail === 'string') return j.detail
    if (Array.isArray(j.detail)) {
      return j.detail
        .map(d => (typeof d?.msg === 'string' ? d.msg : JSON.stringify(d)))
        .filter(Boolean)
        .join('; ')
    }
    if (j.detail != null) return typeof j.detail === 'object' ? JSON.stringify(j.detail) : String(j.detail)
    if (typeof j.message === 'string') return j.message
  } catch {
    /* raw text */
  }
  return t
}

const questionsInflight = new Map()
const questionsCache = new Map()

/**
 * GET /opportunities/{opportunity_id}/questions
 * Returns FE-friendly questions including answer_id + conflict grouping.
 * Deduplicates concurrent requests and reuses last successful JSON per opportunity (unless bypassCache).
 */
export async function fetchOpportunityQuestions(opportunityId, options = {}) {
  const { bypassCache = false } = options
  if (!opportunityId) throw new Error('opportunityId is required')

  if (!bypassCache && questionsCache.has(opportunityId)) {
    if (import.meta.env.DEV) {
      console.info(
        '%c[Data source: Swagger / API — cached]%c GET /opportunities/…/questions',
        'color:#059669;font-weight:700',
        'color:inherit',
        `${API_BASE.replace(/\/$/, '')}/opportunities/${encodeURIComponent(opportunityId)}/questions`,
        {
          opportunity_id: opportunityId,
          questions_count: Array.isArray(questionsCache.get(opportunityId)?.questions)
            ? questionsCache.get(opportunityId).questions.length
            : 0,
        },
      )
    }
    return Promise.resolve(questionsCache.get(opportunityId))
  }
  if (questionsInflight.has(opportunityId)) {
    return questionsInflight.get(opportunityId)
  }

  const encoded = encodeURIComponent(opportunityId)
  const url = `${API_BASE.replace(/\/$/, '')}/opportunities/${encoded}/questions`
  const relUrl = `/opportunities/${encoded}/questions`

  const p = (async () => {
    try {
      const { data } = await api.get(relUrl)
      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / live API]%c GET /opportunities/{id}/questions',
          'color:#2563eb;font-weight:700',
          'color:inherit',
          url,
          { opportunity_id: opportunityId, questions_count: Array.isArray(data?.questions) ? data.questions.length : 0 },
        )
      }
      questionsCache.set(opportunityId, data)
      return data
    } finally {
      questionsInflight.delete(opportunityId)
    }
  })()

  questionsInflight.set(opportunityId, p)
  return p
}

export function clearOpportunityQuestionsCache(opportunityId) {
  if (opportunityId == null) questionsCache.clear()
  else questionsCache.delete(opportunityId)
}

/**
 * Backend contract (strict): only `opp_id` + `updates[]` — **one string `answer_id` per row** (never `answer_id: [uuid1, uuid2]`).
 * - Multi-select: **multiple** `updates[]` entries with the **same** `q_id`, each with a **single** `answer_id` (see `buildOpportunityReviewUpdates`).
 * - Conflict (resolved branch, no text override): **`conflict_id` + `conflict_answer_id` only** — omit `answer_id` (matches product example).
 * - Conflict + user override: `answer_id`, `conflict_id`, `conflict_answer_id`, `is_user_override`, `override_value`.
 * - Non-conflict override: `answer_id`, `is_user_override`, `override_value`.
 */
function normalizeAnswerIdForWire(rawAnswerId, multiFormat) {
  if (rawAnswerId == null) return { kind: 'none' }
  if (Array.isArray(rawAnswerId)) {
    const parts = rawAnswerId.map(x => String(x).trim()).filter(Boolean)
    if (parts.length === 0) return { kind: 'none' }
    if (multiFormat === 'array' || multiFormat === 'json-array' || multiFormat === 'native') {
      return { kind: 'array', value: parts }
    }
    return { kind: 'string', value: parts.join(',') }
  }
  const s = String(rawAnswerId).trim()
  if (s === '') return { kind: 'none' }
  return { kind: 'string', value: s }
}

function sanitizeOneAnswerUpdate(raw) {
  if (raw == null || typeof raw !== 'object') return null
  const qId = raw.q_id != null ? String(raw.q_id).trim() : ''
  if (!qId) return null

  const multiFormat = String(import.meta.env.VITE_POST_ANSWERS_MULTI_SELECT_ANSWER_ID_FORMAT || 'array')
    .toLowerCase()
    .trim()

  const comments = raw.comments != null ? String(raw.comments) : ''
  const hasFeedbackBlock =
    raw.feedback_type != null ||
    (raw.feedback_id != null && String(raw.feedback_id).trim() !== '') ||
    comments.trim() !== ''

  const conflictId =
    raw.conflict_id != null && String(raw.conflict_id).trim() !== '' ? String(raw.conflict_id).trim() : null
  const conflictAnswerId =
    raw.conflict_answer_id != null && String(raw.conflict_answer_id).trim() !== ''
      ? String(raw.conflict_answer_id).trim()
      : null

  const isUserOverride = raw.is_user_override === true
  let overrideValue = null
  if (Array.isArray(raw.override_value)) {
    const arr = raw.override_value.map(x => String(x).trim()).filter(Boolean)
    if (arr.length > 0) overrideValue = arr
  } else if (raw.override_value != null && String(raw.override_value).trim() !== '') {
    overrideValue = String(raw.override_value).trim()
  }

  const aidNorm = normalizeAnswerIdForWire(raw.answer_id, multiFormat)

  /** Backend rejects `is_user_override: true` without a non-empty `override_value`. */
  const effectiveIsUserOverride =
    isUserOverride &&
    overrideValue != null &&
    !(Array.isArray(overrideValue) && overrideValue.length === 0)

  /** @type {Record<string, unknown>} */
  const out = {
    q_id: qId,
  }
  if (hasFeedbackBlock) {
    if (raw.feedback_id != null && String(raw.feedback_id).trim() !== '') {
      out.feedback_id = String(raw.feedback_id).trim()
    }
    if (raw.feedback_type != null) {
      out.feedback_type = normalizeFeedbackTypeForWire(raw.feedback_type)
    }
    if (comments.trim() !== '') out.comments = comments
  }

  if (aidNorm.kind === 'array') {
    out.answer_id = aidNorm.value
  } else if (aidNorm.kind === 'string') {
    out.answer_id = aidNorm.value
  }

  if (conflictId != null) out.conflict_id = conflictId
  if (conflictAnswerId != null) out.conflict_answer_id = conflictAnswerId

  if (effectiveIsUserOverride) {
    out.is_user_override = true
    out.override_value = overrideValue
  }

  const hasConflictPair = Boolean(out.conflict_id && out.conflict_answer_id)
  /** Pure conflict resolution: selected branch UUID only on `conflict_answer_id` (no duplicate `answer_id`). */
  if (hasConflictPair && !effectiveIsUserOverride) {
    delete out.answer_id
  }

  const hasAnswer =
    out.answer_id != null &&
    !(typeof out.answer_id === 'string' && String(out.answer_id).trim() === '') &&
    !(Array.isArray(out.answer_id) && out.answer_id.length === 0)
  const hasOverride = effectiveIsUserOverride
  if (!hasAnswer && !hasOverride && !hasConflictPair) return null
  if (!hasAnswer && !hasConflictPair && hasOverride) return null

  return out
}

function sanitizeAnswersPostBodyForBackend(payload) {
  if (!payload || !Array.isArray(payload.updates)) return payload
  const oppId = payload.opp_id != null ? String(payload.opp_id).trim() : ''
  /** Legacy safety: never send `answer_id` as a multi-element array in one row. */
  const expanded = []
  for (const raw of payload.updates) {
    if (raw == null || typeof raw !== 'object') continue
    const aid = raw.answer_id
    if (Array.isArray(aid) && aid.length > 1) {
      for (const id of aid) {
        expanded.push({ ...raw, answer_id: id })
      }
    } else {
      expanded.push(raw)
    }
  }
  const updates = expanded.map(sanitizeOneAnswerUpdate).filter(Boolean)
  return { opp_id: oppId, updates }
}

function summarizePostUpdatesForDebug(updates) {
  const arr = Array.isArray(updates) ? updates : []
  return arr.slice(0, 60).map(u => {
    const a = u?.answer_id
    const ca = u?.conflict_answer_id
    return {
      q_id: u?.q_id,
      answer_id_type: Array.isArray(a) ? 'array' : typeof a,
      /** `typeof null === 'object'` in JS — use explicit kind for debugging */
      conflict_answer_id_kind: ca === null ? 'null' : Array.isArray(ca) ? 'array' : typeof ca,
      conflict_answer_id_type: Array.isArray(ca) ? 'array' : typeof ca,
      conflict_id: u?.conflict_id ?? null,
      is_user_override: Boolean(u?.is_user_override),
      override_value_type: u?.override_value == null ? null : typeof u?.override_value,
    }
  })
}

/**
 * POST /opportunities/{opportunity_id}/answers
 *
 * Body shape:
 * `{ opp_id: string, updates: Array<{
 *   q_id, answer_id, conflict_id, conflict_answer_id,
 *   feedback_id: string, feedback_type: number (1–5), comments: string,
 *   is_user_override: boolean, override_value?: string | string[]
 * }> }`
 *
 * - Normal pick / text: `answer_id` = string UUID (no `null` keys).
 * - Conflict (branch chosen, no override): `conflict_id` + `conflict_answer_id` only (`answer_id` omitted on wire).
 * - Conflict + user override: `answer_id`, `conflict_id`, `conflict_answer_id`, `is_user_override`, `override_value`.
 * - Non-conflict user override: `answer_id`, `is_user_override`, `override_value`.
 * - Multi-select: **several** update objects with the same `q_id`, each with **one** string `answer_id`.
 *
 * Built by `buildOpportunityReviewUpdates` in `opportunityReviewMeta.js` from merged `apiSelections` + `qState`.
 * Option `id` values must match backend answer ids (from GET /questions or answer rows), not display text.
 *
 * @param {string} opportunityId
 * @param {{ opp_id?: string, updates: Array<Record<string, unknown>> }} payload
 * @returns {Promise<Record<string, unknown>>} Parsed JSON response body.
 */
export async function postOpportunityUpdates(opportunityId, payload) {
  if (!opportunityId) throw new Error('opportunityId is required')
  const encoded = encodeURIComponent(opportunityId)
  const url = `${API_BASE.replace(/\/$/, '')}/opportunities/${encoded}/answers`
  const relUrl = `/opportunities/${encoded}/answers`
  const bodyPayload = sanitizeAnswersPostBodyForBackend(payload)
  const wireJson = JSON.stringify(bodyPayload, null, 2)
  if (import.meta.env.DEV) {
    console.info('[Submit Payload Raw]', payload)
    console.info('[Submit Payload Sanitized]', bodyPayload)
    console.info(
      '%c[Data source: Swagger / live API]%c POST /opportunities/{id}/answers',
      'color:#7c3aed;font-weight:700',
      'color:inherit',
      url,
      { opp_id: bodyPayload.opp_id, updatesCount: bodyPayload.updates?.length ?? 0 },
    )
    console.info(
      '%c[POST /answers] exact wire JSON (per q_id in `updates[]`)%c\n%s',
      'color:#0ea5e9;font-weight:700',
      'color:inherit',
      wireJson,
    )
    console.info(
      '%c[POST /answers] updates field summary (types only)%c',
      'color:#7c3aed;font-weight:700',
      'color:inherit',
      summarizePostUpdatesForDebug(bodyPayload.updates),
    )
  }
  try {
    const { data } = await api.post(relUrl, bodyPayload, {
      headers: { 'Content-Type': 'application/json' },
    })
    if (import.meta.env.DEV) {
      console.info('%c[Data source: Swagger / live API]%c POST response', 'color:#7c3aed;font-weight:700', 'color:inherit', data)
    }
    return data
  } catch (e) {
    const status = e?.response?.status
    const responseText =
      typeof e?.response?.data === 'string'
        ? e.response.data
        : e?.response?.data != null
          ? JSON.stringify(e.response.data)
          : ''
    const detail = formatOpportunityReviewApiErrorBody(responseText)
    const qids = Array.isArray(payload?.updates)
      ? payload.updates.map(u => String(u?.q_id ?? '')).filter(Boolean)
      : []
    if (import.meta.env.DEV) {
      console.error(
        '%c[POST /answers] HTTP error body%c',
        'color:#dc2626;font-weight:700',
        'color:inherit',
        { status: status ?? null, detail, responseText },
      )
      console.error(
        '%c[POST /answers] same request JSON that failed (for copy/paste)%c\n%s',
        'color:#dc2626;font-weight:700',
        'color:inherit',
        wireJson,
      )
      console.error('[POST /answers] failed payload', payload)
    }
    const withQids = qids.length ? `${detail} [q_ids: ${qids.join(', ')}]` : detail
    throw new Error(
      withQids ||
        detail ||
        (status
          ? `Request failed (${status}): ${responseText || e?.message || ''}`
          : e?.message || 'Request failed'),
    )
  }
}
