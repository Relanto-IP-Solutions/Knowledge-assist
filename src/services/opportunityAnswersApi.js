import { inferSourceTypeFromCitationFields } from '../utils/citationSourceInference'
import { enrichAnswerRowAfterNormalize } from '../utils/enrichAnswerIds'
import { serializeAssistMultiValue } from '../utils/opportunityAnswerRowToReviewQuestion'
import { api } from './apiClient'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/** String or array (e.g. multi-select) → stable string for UI + conflict matching */
export function normalizeAnswerValueField(v) {
  if (v == null) return null
  if (Array.isArray(v)) {
    const parts = v.map(x => String(x).trim()).filter(Boolean)
    if (!parts.length) return null
    return serializeAssistMultiValue(parts)
  }
  const s = String(v).trim()
  return s === '' ? null : s
}

/**
 * @typedef {Object} Citation
 * @property {string} source_type
 * @property {string} source_file
 * @property {string} source_name
 * @property {string|null} document_date
 * @property {string} chunk_id
 * @property {string} quote
 * @property {string|null} context
 * @property {number|null} page_number
 * @property {string|null} timestamp_str
 * @property {string|null} speaker
 * @property {number} relevance_score
 * @property {boolean} is_primary
 */

/**
 * @typedef {Object} ConflictEntry
 * @property {string} answer_value
 * @property {number} confidence_score
 * @property {Citation[]} citations
 */

/**
 * @typedef {Object} OpportunityAnswerRow
 * @property {string} question_id
 * @property {string|null} answer_value
 * @property {number} confidence_score
 * @property {Citation[]} citations
 * @property {string|null} conflict_id
 * @property {ConflictEntry[]} conflicts
 * @property {string|null} [answer_id] Primary / recommended answer id when the row includes conflicts (for submit)
 * @property {string[]|undefined} [selected_answer_ids] Canonical ids for multi-select when raw `answer_value` was an array
 * @property {string} [status] Row lifecycle from GET /answers (e.g. pending, active); used for POST eligibility, not primary UI
 */

/**
 * @typedef {Object} OpportunityAnswersResponse
 * @property {string} opportunity_id
 * @property {OpportunityAnswerRow[]} answers
 * @property {number} [human_count]
 * @property {number} [ai_count]
 * @property {number} [total_questions]
 * @property {number} [percentage] Overall completion 0–100
 * @property {number} [human_percentage] Human-reviewed share 0–100
 * @property {number} [ai_percentage] AI-only share 0–100
 */

const answersInflight = new Map()
const answersCache = new Map()

/**
 * `question_id`s that already have conflicts in the **raw** GET /answers JSON (Swagger response body),
 * before `normalizeAnswerRow` merges mock `oid0009ConflictOverrides` rows.
 *
 * Counts a row if `conflicts[]` is non-empty and/or `conflict_id` is set.
 *
 * @param {unknown} rawPayload - e.g. `{ answers?: unknown[] }`
 * @returns {string[]}
 */
export function listQuestionIdsWithConflictsInApiResponse(rawPayload) {
  const rows = rawPayload?.answers
  if (!Array.isArray(rows)) return []
  const out = []
  for (const a of rows) {
    if (a == null || typeof a !== 'object') continue
    const qid = a.question_id
    if (qid == null || String(qid).trim() === '') continue
    const conflicts = a.conflicts
    const hasConflicts = Array.isArray(conflicts) && conflicts.length > 0
    const cid = a.conflict_id
    const hasConflictId = cid != null && String(cid).trim() !== ''
    if (hasConflicts || hasConflictId) out.push(String(qid))
  }
  return out
}

/**
 * DEV: log GET /answers body like POST’s “exact wire JSON” — copy/paste to compare with saved JSON files.
 * @param {string} opportunityId
 * @param {string} url
 * @param {unknown} data
 * @param {'live'|'cached'} source
 */
function devLogGetAnswersResponseWireJson(opportunityId, url, data, source) {
  if (!import.meta.env.DEV || data == null) return
  const rows = data?.answers
  const n = Array.isArray(rows) ? rows.length : 0
  const oid = data?.opportunity_id ?? opportunityId
  console.info(
    '%c[GET /answers] response summary%c',
    'color:#2563eb;font-weight:700',
    'color:inherit',
    { source, url, opportunity_id: oid, answersCount: n },
  )
  try {
    const wire = JSON.stringify(data, null, 2)
    console.info(
      '%c[GET /answers] exact response JSON (copy/paste)%c\n%s',
      'color:#0ea5e9;font-weight:700',
      'color:inherit',
      wire,
    )
  } catch (e) {
    console.warn('[GET /answers] could not stringify response', e, data)
  }
}

function devLogConflictsFromSwaggerAnswers(label, data) {
  if (!import.meta.env.DEV || data == null) return
  const ids = listQuestionIdsWithConflictsInApiResponse(data)
  if (ids.length === 0) {
    console.info(
      `%c[API GET /answers: conflicts]%c ${label} — none in response body (no non-empty conflicts[] and no conflict_id on rows).`,
      'color:#0369a1;font-weight:700',
      'color:inherit',
    )
    return
  }
  console.info(
    `%c[API GET /answers: conflicts]%c ${label} — from Swagger/API body only (not mock): %c${ids.join(', ')}`,
    'color:#0369a1;font-weight:700',
    'color:inherit',
    'color:#0f172a;font-weight:600',
  )
}

/**
 * GET /opportunities/{oid}/answers
 * Deduplicates concurrent requests and reuses the last successful JSON per opportunity (unless bypassCache).
 * @param {string} opportunityId - backend opportunity id
 * @param {{ bypassCache?: boolean }} [options]
 * @returns {Promise<OpportunityAnswersResponse>}
 */
export async function fetchOpportunityAnswers(opportunityId, options = {}) {
  const { bypassCache = false } = options
  if (!opportunityId) throw new Error('opportunityId is required')

  if (!bypassCache && answersCache.has(opportunityId)) {
    if (import.meta.env.DEV) {
      const cachedUrl = `${API_BASE.replace(/\/$/, '')}/opportunities/${encodeURIComponent(opportunityId)}/answers`
      const cached = answersCache.get(opportunityId)
      console.info(
        '%c[Data source: Swagger / API — cached]%c GET /opportunities/…/answers (same JSON as last live response)',
        'color:#059669;font-weight:700',
        'color:inherit',
        cachedUrl,
        cached,
      )
      devLogGetAnswersResponseWireJson(opportunityId, cachedUrl, cached, 'cached')
      devLogConflictsFromSwaggerAnswers('cached payload', cached)
    }
    return Promise.resolve(answersCache.get(opportunityId))
  }
  if (answersInflight.has(opportunityId)) {
    return answersInflight.get(opportunityId)
  }

  const encoded = encodeURIComponent(opportunityId)
  const url = `${API_BASE.replace(/\/$/, '')}/opportunities/${encoded}/answers`

  const relUrl = `/opportunities/${encoded}/answers`

  const p = (async () => {
    try {
      const { data } = await api.get(relUrl)
      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / live API]%c GET /opportunities/{id}/answers — response body matches your OpenAPI/Swagger schema',
          'color:#2563eb;font-weight:700',
          'color:inherit',
          url,
          data,
        )
        devLogGetAnswersResponseWireJson(opportunityId, url, data, 'live')
        devLogConflictsFromSwaggerAnswers('live response', data)
      }
      answersCache.set(opportunityId, data)
      return data
    } finally {
      answersInflight.delete(opportunityId)
    }
  })()

  answersInflight.set(opportunityId, p)
  return p
}

/** Drop cached GET /answers for one id (or all if omitted). */
export function clearOpportunityAnswersCache(opportunityId) {
  if (opportunityId == null) answersCache.clear()
  else answersCache.delete(opportunityId)
}

/**
 * @param {unknown} raw
 * @returns {unknown[]|null}
 */
function coerceToCitationArray(raw) {
  if (raw == null) return null
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string') {
    const t = raw.trim()
    if (!t) return null
    try {
      const p = JSON.parse(t)
      return Array.isArray(p) ? p : null
    } catch {
      return null
    }
  }
  if (typeof raw === 'object') {
    const vals = Object.values(raw)
    if (vals.length && vals.every(v => v != null && typeof v === 'object' && !Array.isArray(v))) return vals
  }
  return null
}

/**
 * Collect citations from GET /answers rows — supports snake_case, camelCase, JSON strings, and map-shaped payloads.
 * @param {Record<string, unknown>} row
 * @returns {unknown[]}
 */
export function extractCitationsFromRawAnswerRow(row) {
  if (row == null || typeof row !== 'object') return []
  const keys = [
    'citations',
    'Citations',
    'evidence',
    'evidence_chunks',
    'evidenceChunks',
    'source_citations',
    'sourceCitations',
    'source_excerpts',
    'sourceExcerpts',
    'sources',
    'citation_list',
    'citationList',
    'answer_citations',
    'answerCitations',
  ]
  for (const k of keys) {
    if (!Object.prototype.hasOwnProperty.call(row, k)) continue
    const coerced = coerceToCitationArray(row[k])
    if (coerced?.length) return coerced
  }
  return []
}

/**
 * GET /answers often sends `citations: []` on the row but full excerpts under `conflicts[].citations`.
 * Collect raw citation objects from every conflict entry (before normalizeConflictEntry).
 * @param {Record<string, unknown>} row
 */
function extractRawCitationsFromConflicts(row) {
  const out = []
  const conflicts = row.conflicts
  if (!Array.isArray(conflicts)) return out
  for (const ent of conflicts) {
    if (!ent || typeof ent !== 'object') continue
    const list = ent.citations ?? ent.Citations
    if (!Array.isArray(list)) continue
    for (const cit of list) {
      if (cit != null && typeof cit === 'object') out.push(cit)
    }
  }
  return out
}

function dedupeRawCitationObjects(rawArray) {
  const seen = new Set()
  const out = []
  for (const c of rawArray) {
    if (c == null || typeof c !== 'object') continue
    const cid = String(c.chunk_id ?? c.chunkId ?? '')
    const key = cid || `fallback-${out.length}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(c)
  }
  return out
}

/** Top-level `citations` ∪ each `conflicts[].citations` (deduped by chunk_id). */
function gatherRawCitationsFromAnswerRow(row) {
  const fromTop = extractCitationsFromRawAnswerRow(row)
  const fromConf = extractRawCitationsFromConflicts(row)
  return dedupeRawCitationObjects([...fromTop, ...fromConf])
}

function dedupeNormalizedCitationList(list) {
  const seen = new Set()
  const out = []
  for (const c of list) {
    if (!c || typeof c !== 'object') continue
    const cid = String(c.chunk_id ?? '')
    const key = cid || `i-${out.length}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(c)
  }
  return out
}

/**
 * Normalizes one answer row for UI (safe arrays, strings).
 * Fills missing `answer_id` / conflict `answer_id` / `conflict_id` from piclist catalog or stable synthetic ids
 * (matches oid0009-style exports that only had `answer_value` + `conflicts[].answer_value`).
 * @param {Record<string, unknown>} row
 * @param {{ opportunityId?: string, preferApiAnswerIds?: boolean }} [context]
 *   When `preferApiAnswerIds` is not `false` and `opportunityId` is set, skip piclist-based id inference so
 *   GET /answers rows keep backend UUIDs only (better POST /answers payloads).
 */
export function normalizeAnswerRow(row, context = {}) {
  const rawList = gatherRawCitationsFromAnswerRow(row)
  let citations = rawList.map(normalizeCitation)
  const answer_value = normalizeAnswerValueField(row.answer_value ?? row.value ?? row.answerValue)
  const confidence_score = typeof row.confidence_score === 'number' ? row.confidence_score : 0

  /** Backend row status (POST only includes rows with status === pending). Preserve common API aliases. */
  const rawStatus = row.status ?? row.answer_status ?? row.AnswerStatus
  const status =
    rawStatus != null && String(rawStatus).trim() !== '' ? String(rawStatus).trim() : ''

  let conflicts = Array.isArray(row.conflicts) ? row.conflicts.map(normalizeConflictEntry) : []

  const base = {
    question_id: String(row.question_id ?? ''),
    answer_id: row.answer_id != null && String(row.answer_id).trim() !== '' ? String(row.answer_id) : null,
    answer_value,
    status,
    answer_type: row.answer_type != null ? String(row.answer_type) : null,
    requirement_type: row.requirement_type != null ? String(row.requirement_type) : null,
    question_text: row.question_text != null ? String(row.question_text) : null,
    confidence_score,
    citations,
    conflict_id: row.conflict_id ? String(row.conflict_id) : null,
    conflicts,
    ...(typeof row.current_version === 'number' ? { current_version: row.current_version } : {}),
    ...(row.status != null && String(row.status).trim() !== ''
      ? { status: String(row.status).trim() }
      : {}),
    ...(context.opportunityId != null ? { opportunity_id: String(context.opportunityId) } : {}),
  }

  // Safety: preserve any non-empty API answer_value as-is (trimmed)
  if (
    row.answer_value != null &&
    String(row.answer_value).trim() !== ''
  ) {
    base.answer_value = String(row.answer_value).trim()
  }

  const oid = context.opportunityId != null ? String(context.opportunityId) : ''
  const skipPiclistInference =
    context.preferApiAnswerIds !== false && oid.trim() !== ''
  const normalized = enrichAnswerRowAfterNormalize(base, row, oid, { skipPiclistInference })
  return normalized
}

/**
 * Last-chance merge for Sources tab from live GET /answers payload only.
 * @param {Record<string, unknown>} row
 * @returns {object[]}
 */
export function finalizeCitationsForDisplay(row) {
  let list = Array.isArray(row.citations) ? [...row.citations] : []
  if (list.length === 0 && Array.isArray(row.conflicts)) {
    for (const c of row.conflicts) {
      if (c && Array.isArray(c.citations) && c.citations.length) {
        list.push(...c.citations)
      }
    }
    list = dedupeNormalizedCitationList(list)
  }
  if (list.length > 0) return list
  return list
}

/**
 * Normalizes a single citation object.
 * @param {Record<string, unknown>} c
 * @returns {Citation}
 */
function normalizeCitation(c) {
  if (c == null || typeof c !== 'object') return { source_type: 'unknown', source_file: '', source_name: '', document_date: null, chunk_id: '', quote: String(c ?? ''), context: null, page_number: null, timestamp_str: null, speaker: null, relevance_score: 0, is_primary: false }
  const source_file = String(
    c.source_file ?? c.sourceFile ?? c.file_path ?? c.filePath ?? '',
  )
  const source_name = String(
    c.source_name ?? c.sourceName ?? c.source_document ?? c.sourceDocument ?? '',
  )
  const source_type = inferSourceTypeFromCitationFields({
    source_type: c.source_type ?? c.sourceType,
    source_file,
    source_name,
  })
  let relevance_score = 0
  if (typeof c.relevance_score === 'number') relevance_score = c.relevance_score
  else if (typeof c.relevanceScore === 'number') relevance_score = c.relevanceScore
  return {
    source_type: String(source_type || 'unknown'),
    source_file,
    source_name,
    document_date: c.document_date ?? c.documentDate ?? null,
    chunk_id: String(c.chunk_id ?? c.chunkId ?? ''),
    quote: String(c.quote ?? c.text ?? c.excerpt ?? c.snippet ?? c.source_chunk ?? ''),
    context: c.context ?? null,
    page_number: c.page_number ?? c.pageNumber ?? null,
    timestamp_str: c.timestamp_str ?? c.timestampStr ?? null,
    speaker: c.speaker ?? null,
    relevance_score,
    is_primary: Boolean(c.is_primary ?? c.isPrimary),
  }
}

/**
 * Normalizes a single conflict entry.
 * @param {Record<string, unknown>} entry
 * @returns {ConflictEntry}
 */
function normalizeConflictEntry(entry) {
  if (entry == null || typeof entry !== 'object') return { answer_id: null, answer_value: String(entry ?? ''), confidence_score: 0, citations: [] }
  const rawConflictCites = extractCitationsFromRawAnswerRow(entry)
  const citations = rawConflictCites.length ? rawConflictCites.map(normalizeCitation) : []
  const avRaw = entry.answer_value ?? entry.value ?? entry.answerValue
  return {
    answer_id: entry.answer_id != null ? String(entry.answer_id) : null,
    answer_value: avRaw != null ? String(avRaw) : '',
    confidence_score: typeof entry.confidence_score === 'number' ? entry.confidence_score : 0,
    citations,
  }
}
