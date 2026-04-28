import {
  getPiclistAnswerRowsForQuestion,
  getPiclistStudioRowsForQuestion,
  matchPiclistValueToAnswerId,
} from '../config/piclistOptionsByQid'
import { inferConflictGroupId } from './enrichAnswerIds'
import { parseSerializedListAnswerValue, serializeAssistMultiValue } from './opportunityAnswerRowToReviewQuestion'
import { isAnswerOverride } from './overrideDetection'

/** DEV: avoid spamming the console when id alignment runs on every effect pass */
const __devUnmappedPostAnswerIds = new Set()

/**
 * Canonical Map key for `question_id` / `q_id` in POST merge paths (trimmed string; `''` if missing).
 */
function postMapQidKey(qid) {
  if (qid == null) return ''
  return String(qid).trim()
}

function normalizeBooleanLike(value) {
  if (value === true || value === false) return value
  const t = String(value ?? '').trim().toLowerCase()
  if (t === 'true' || t === '1' || t === 'yes') return true
  if (t === 'false' || t === '0' || t === 'no') return false
  return null
}

/** Placeholder when GET /answers has no extraction (UI + POST coercion must agree). */
export const NO_EXTRACTED_ANSWER_TEXT = 'No extracted answer available for this question.'

/** Generate a simple feedback ID for demo purposes */
function generateFeedbackId() {
  return String(Math.floor(Math.random() * 9000) + 1000)
}

/** Backend expects `feedback_type` as integer 1–5 (default 4 when the user did not rate). */
export function normalizeFeedbackTypeForWire(feedback) {
  const d = 4
  if (feedback == null || feedback === '') return d
  const n =
    typeof feedback === 'number' && Number.isFinite(feedback)
      ? Math.round(feedback)
      : parseInt(String(feedback).trim(), 10)
  if (Number.isNaN(n)) return d
  return Math.min(5, Math.max(1, n))
}

/**
 * Normalizes GET /opportunities/{id}/questions rows for review UI + submit validation.
 */

export function normalizeAnswerType(q) {
  const raw = String(q?.answer_type ?? q?.answerType ?? q?.question_answer_type ?? '')
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
  if (['picklist', 'single_select', 'radio', 'choice', 'dropdown'].includes(raw)) return 'picklist'
  if (['multi_select', 'multiselect', 'checkbox', 'multi', 'multiple', 'list'].includes(raw)) return 'multi_select'
  return 'text'
}

/**
 * One row from answers[], answer_value[], etc. → { id, text } for radios / checkboxes.
 * Primitives become id === text (value sent back as answer_id).
 */
export function mapAnswerOptionRow(a, i) {
  if (a == null) return null
  if (typeof a === 'string' || typeof a === 'number' || typeof a === 'boolean') {
    const text = String(a).trim()
    if (!text) return null
    return { id: text, text }
  }
  const rawId = a.answer_id ?? a.id ?? a.answerId ?? a.option_id ?? a.optionId
  const text =
    a.answer_value ?? a.value ?? a.text ?? a.answer_text ?? a.label ?? a.title ?? ''
  const id = rawId != null && String(rawId).trim() !== '' ? String(rawId) : null
  const t = String(text).trim()
  if (!id && !t) return null
  return {
    id: id ?? `row:${i}`,
    text: t || id || `Option ${i + 1}`,
  }
}

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

/** True when this answer row has competing extractions (do not replace `answers[]` with GET /questions picklist options). */
export function hasExtractedAnswerConflicts(row) {
  if (!row) return false
  if (row.conflict_id != null && String(row.conflict_id).trim() !== '') return true
  if (Array.isArray(row.conflicts) && row.conflicts.length > 0) return true
  return false
}

/**
 * Non-null `conflict_id` for POST when GET /answers has competing options.
 * Prefers the raw row’s id, then the merged review question, then a stable inferred group id.
 * @param {Record<string, unknown>} rawRow
 * @param {Record<string, unknown>} q - review question
 * @param {string|null|undefined} opportunityId
 * @returns {string|null}
 */
export function resolveConflictIdForPost(rawRow, q, opportunityId) {
  const qid = q?.question_id != null ? String(q.question_id) : ''
  const oid =
    opportunityId != null && String(opportunityId).trim() !== ''
      ? String(opportunityId).trim()
      : null

  const fromRaw = rawRow?.conflict_id != null ? String(rawRow.conflict_id).trim() : ''
  const fromQ = q?.conflict?.conflict_id != null ? String(q.conflict.conflict_id).trim() : ''

  const hasConflict =
    hasExtractedAnswerConflicts(rawRow) || Boolean(fromQ) || Boolean(fromRaw)

  if (!hasConflict) return null

  // Only return real (backend-provided) conflict_ids, never synthetic/inferred ones.
  // Synthetic ids (e.g. `{oid}:{qid}:conflict`) cause backend POST failures because
  // the `conflicts` table does not contain them.
  if (fromRaw && !isFrontendInferredConflictGroupId(fromRaw, oid, qid)) return fromRaw
  if (fromQ && !isFrontendInferredConflictGroupId(fromQ, oid, qid)) return fromQ
  return null
}

/**
 * Ensures each POST update for a row with extraction conflicts includes a non-empty `conflict_id`.
 * @param {unknown[]} updates
 * @param {unknown[]} rawAnswerRows
 * @returns {{ ok: boolean, message: string, qids: string[] }}
 */
export function validatePostConflictIds(updates, rawAnswerRows) {
  const byQ = new Map(
    (rawAnswerRows || []).map(r => [postMapQidKey(r.question_id), r]).filter(([k]) => k),
  )
  const bad = []
  for (const u of updates || []) {
    const qid = u?.q_id != null ? postMapQidKey(u.q_id) : ''
    if (!qid) continue
    const row = byQ.get(qid)
    if (!row || !hasExtractedAnswerConflicts(row)) continue
    // Skip enforcement when the row's conflict_id is a frontend-inferred synthetic id
    // (e.g. `{oid}:{qid}:conflict`). These don't exist in the backend `conflicts` table,
    // so requiring them in the POST would always fail.
    const rowCid = row?.conflict_id != null ? String(row.conflict_id).trim() : ''
    if (rowCid && isFrontendInferredConflictGroupId(rowCid, null, qid)) continue
    // Also skip if the row has no real conflict_id at all (only conflicts[] array)
    if (!rowCid && Array.isArray(row?.conflicts) && row.conflicts.length > 0) continue
    // User-entered overrides are submitted with conflict_id: null intentionally; do not require it
    if (u?.is_user_override === true) continue
    const cid = u?.conflict_id
    if (cid == null || String(cid).trim() === '') bad.push(qid)
  }
  return {
    ok: bad.length === 0,
    qids: bad,
    message:
      bad.length === 0
        ? ''
        : bad.length <= 4
          ? `Missing conflict_id for conflicting answers (${bad.join(', ')}).`
          : `Missing conflict_id for ${bad.length} conflicting answers.`,
  }
}

function pickFirstCatalogScalar(qCatalog, keys) {
  for (const k of keys) {
    const v = qCatalog[k]
    if (v === undefined || v === null) continue
    if (typeof v === 'string' && v.trim() === '') continue
    return v
  }
  return undefined
}

/**
 * Overlay GET /opportunities/{id}/questions row onto a normalized GET /answers row:
 * `answer_type`, requirement flags, `question_text`, and option arrays (when no extraction conflicts).
 * @param {Record<string, unknown>|null|undefined} answerRow
 * @param {Record<string, unknown>|null|undefined} qCatalog
 */
export function mergeAnswerRowWithQuestionsCatalog(answerRow, qCatalog) {
  if (!answerRow || !qCatalog) return answerRow

  const out = { ...answerRow }

  const at = pickFirstCatalogScalar(qCatalog, [
    'answer_type',
    'answerType',
    'question_answer_type',
    'questionAnswerType',
  ])
  if (at !== undefined) out.answer_type = String(at)

  if (qCatalog.is_required === true || qCatalog.required === true) {
    if (!out.requirement_type || String(out.requirement_type).trim() === '') {
      out.requirement_type = 'required'
    }
  }
  const rt = pickFirstCatalogScalar(qCatalog, ['requirement_type', 'requirementType'])
  if (rt !== undefined) out.requirement_type = String(rt)

  const qt = pickFirstCatalogScalar(qCatalog, ['question_text', 'questionText'])
  if (qt !== undefined && (!out.question_text || String(out.question_text).trim() === '')) {
    out.question_text = String(qt)
  }

  if (hasExtractedAnswerConflicts(out)) return out

  for (const k of ROW_OPTION_KEYS) {
    const v = qCatalog[k]
    if (Array.isArray(v) && v.length > 0) out[k] = v
  }
  for (const k of ['option_values', 'optionValues', 'answer_values', 'answerValues']) {
    const v = qCatalog[k]
    if (Array.isArray(v) && v.length > 0) out[k] = v
  }

  return out
}

function firstNonEmptyList(q, keys) {
  for (const k of keys) {
    const v = q?.[k]
    if (Array.isArray(v) && v.length > 0) return v
  }
  return null
}

/** e.g. ['REST', 'GraphQL'] — use checkboxes, not picklist radios. */
function listIsAllPrimitiveItems(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return false
  return arr.every(
    x => x == null || typeof x === 'string' || typeof x === 'number' || typeof x === 'boolean',
  )
}

/**
 * @returns {{ mapped: { id: string, text: string }[], primitiveList: boolean } | null}
 */
function resolveReviewOptionSource(q) {
  const fromRows = firstNonEmptyList(q, ROW_OPTION_KEYS)
  if (fromRows) {
    let mapped = fromRows.map(mapAnswerOptionRow).filter(Boolean)
    if (
      normalizeAnswerType(q) === 'multi_select' &&
      mapped.length === 1 &&
      typeof mapped[0]?.text === 'string' &&
      String(mapped[0].text).trim().startsWith('[')
    ) {
      const expanded = parseSerializedListAnswerValue(mapped[0].text)
        .map(v => {
          const t = String(v ?? '').trim()
          return t ? { id: t, text: t } : null
        })
        .filter(Boolean)
      if (expanded.length > 0) mapped = expanded
    }
    if (mapped.length > 0) {
      return applyPiclistCatalogFallback(q, {
        mapped,
        primitiveList: listIsAllPrimitiveItems(fromRows),
        /** Only treat as authoritative when the API sent multiple choices; a single row is often “current answer only”. */
        trustMappedIds: mapped.length > 1,
      })
    }
  }

  const listFromValue =
    q?.answer_value ??
    q?.answerValue ??
    q?.answer_values ??
    q?.answerValues ??
    q?.option_values ??
    q?.optionValues

  if (Array.isArray(listFromValue) && listFromValue.length > 0) {
    const mapped = listFromValue.map(mapAnswerOptionRow).filter(Boolean)
    if (mapped.length > 0) {
      return applyPiclistCatalogFallback(q, {
        mapped,
        primitiveList: listIsAllPrimitiveItems(listFromValue),
      })
    }
  }

  const at = normalizeAnswerType(q)
  const av = q?.answer_value ?? q?.answerValue
  if (typeof av === 'string' && av.trim() !== '') {
    const parsed = parseSerializedListAnswerValue(av)
    if (parsed.length > 0) {
      const mapped = parsed.map((t, i) => mapAnswerOptionRow(t, i)).filter(Boolean)
      if (mapped.length > 0) {
        return applyPiclistCatalogFallback(q, {
          mapped,
          primitiveList: listIsAllPrimitiveItems(parsed),
        })
      }
    }
    if ((at === 'picklist' || at === 'multi_select') && !av.trim().startsWith('[')) {
      const text = av.trim()
      return applyPiclistCatalogFallback(q, {
        mapped: [{ id: text, text }],
        primitiveList: at === 'multi_select',
        /** Placeholder row so we resolve options; value may be label or answer_id UUID — not a full GET /questions option list. */
        syntheticAnswerValueScalar: true,
      })
    }
  }

  return applyPiclistCatalogFallback(q, null)
}

/**
 * When API returns only the chosen value(s) for a piclist/multi question, use studio piclist rows
 * so the UI shows every option; submit still uses answer_id from the catalog.
 * @param {Record<string, unknown>} q
 * @param {{ mapped: { id: string, text: string }[], primitiveList: boolean, trustMappedIds?: boolean, syntheticAnswerValueScalar?: boolean } | null} resolved
 */
function applyPiclistCatalogFallback(q, resolved) {
  // Live API only: do not fallback to static piclist/studio catalog for review options.
  return resolved
}

/** True when options are a string/number list like ['REST','GraphQL'] (multiselect UI). */
export function reviewOptionsArePrimitiveList(q) {
  return Boolean(resolveReviewOptionSource(q)?.primitiveList)
}

/**
 * Candidate options: structured rows first; else picklist/multiselect lists on answer_value (and aliases).
 * @returns {{ id: string, text: string }[]}
 */
export function reviewAnswerOptions(q) {
  return resolveReviewOptionSource(q)?.mapped ?? []
}

const __assistPicklistLabelKey = (t) =>
  String(t ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')

/**
 * When the merged review row only has one picklist option in `answers[]`, the assist UI would show a single radio.
 * Merge in the full studio piclist for labels; where label matches a sparse row whose `id` is a backend UUID, keep that UUID so selection stays aligned with GET /answers.
 */
export function expandReviewPicklistOptionsForAssistUi(questionId, sparseOpts) {
  const base = Array.isArray(sparseOpts) ? sparseOpts : []
  const catalogRows = getPiclistAnswerRowsForQuestion(questionId)
  if (!catalogRows.length || catalogRows.length <= base.length) return base
  const catalogMapped = catalogRows.map((row, i) => mapAnswerOptionRow(row, i)).filter(Boolean)
  if (catalogMapped.length <= base.length) return base
  const byLabel = new Map()
  for (const o of base) {
    const k = __assistPicklistLabelKey(o.text)
    if (k) byLabel.set(k, o)
  }
  return catalogMapped.map(o => {
    const k = __assistPicklistLabelKey(o.text)
    const hit = k ? byLabel.get(k) : null
    if (hit && looksLikeUuid(String(hit.id))) return { id: String(hit.id), text: o.text }
    return o
  })
}

/**
 * Multi-select equivalent of {@link expandReviewPicklistOptionsForAssistUi}.
 * Ensures the assist UI shows the full checkbox list (from studio piclist catalog),
 * while preserving backend UUID ids when they exist in sparse GET /questions rows.
 */
export function expandReviewMultiSelectOptionsForAssistUi(questionId, sparseOpts) {
  const base = Array.isArray(sparseOpts) ? sparseOpts : []
  const catalogRows = getPiclistAnswerRowsForQuestion(questionId)
  if (!catalogRows.length || catalogRows.length <= base.length) return base
  const catalogMapped = catalogRows.map((row, i) => mapAnswerOptionRow(row, i)).filter(Boolean)
  if (catalogMapped.length <= base.length) return base
  const byLabel = new Map()
  for (const o of base) {
    const k = __assistPicklistLabelKey(o.text)
    if (k) byLabel.set(k, o)
  }
  return catalogMapped.map(o => {
    const k = __assistPicklistLabelKey(o.text)
    const hit = k ? byLabel.get(k) : null
    if (hit && looksLikeUuid(String(hit.id))) return { id: String(hit.id), text: o.text }
    return o
  })
}

/** Plain-text preview when question is not shown as picklist / multiselect. */
export function reviewStaticAnswerPreview(q) {
  const av = q?.answer_value ?? q?.answerValue
  if (Array.isArray(av) && av.length) {
    return av
      .map((x, i) => {
        if (x != null && typeof x === 'object' && !Array.isArray(x)) {
          return mapAnswerOptionRow(x, i)?.text
        }
        return x != null ? String(x).trim() : ''
      })
      .filter(Boolean)
      .join(', ')
  }
  if (typeof av === 'string' && av.trim() && av.trim() !== 'No extracted answer available for this question.') return av.trim()
  const o = reviewAnswerOptions(q)[0]?.text
  if (o && o !== 'No extracted answer available for this question.') return o
  const row0 = q?.answers?.[0]
  if (row0 && typeof row0 === 'object') {
    const t = row0.answer_value ?? row0.value ?? row0.text
    if (t != null && String(t).trim() && String(t).trim() !== 'No extracted answer available for this question.') return String(t).trim()
  }
  return ''
}

/**
 * True when GET /answers data has real extracted/selected content (not blank, not the no-extraction placeholder).
 * Uses the same review row shape as {@link opportunityAnswerRowToReviewQuestion} plus the normalized answer row.
 * Accept-all skips `false` rows only; non-empty rows are eligible to be marked accepted.
 *
 * @param {Record<string, unknown>|null|undefined} q - review question from `opportunityAnswerRowToReviewQuestion`
 * @param {Record<string, unknown>} rawAnswerRow - normalized row from GET /answers (bundle)
 */
export function reviewAnswerRowHasNonEmptyPayload(q, rawAnswerRow) {
  if (rawAnswerRow == null || typeof rawAnswerRow !== 'object') return false

  const conflicts = Array.isArray(rawAnswerRow.conflicts) ? rawAnswerRow.conflicts : []
  if (
    conflicts.some(c => {
      const t = c?.answer_value != null ? String(c.answer_value).trim() : ''
      return t !== '' && t !== NO_EXTRACTED_ANSWER_TEXT
    })
  ) {
    return true
  }

  if (!q || typeof q !== 'object') {
    return nonEmptyAnswerValueField(rawAnswerRow.answer_value)
  }

  const conflictId = Boolean(q.conflict?.conflict_id)
  const opts = reviewAnswerOptions(q)
  const n = opts.length
  const multi = isReviewMultiSelectMode(q, n, conflictId)
  const pick = isReviewPicklistRadiosMode(q, n, conflictId)

  if (multi) {
    if (Array.isArray(q.selected_answer_ids) && q.selected_answer_ids.length > 0) return true
    if (
      Array.isArray(rawAnswerRow.selected_answer_ids) &&
      rawAnswerRow.selected_answer_ids.some(x => x != null && String(x).trim() !== '')
    ) {
      return true
    }
    return nonEmptyAnswerValueField(rawAnswerRow.answer_value)
  }

  if (pick) {
    if (q.final_answer_id != null && String(q.final_answer_id).trim() !== '') {
      return String(q.final_answer_id).trim() !== NO_EXTRACTED_ANSWER_TEXT
    }
    if (rawAnswerRow.answer_id != null && String(rawAnswerRow.answer_id).trim() !== '') return true
    return nonEmptyAnswerValueField(rawAnswerRow.answer_value)
  }

  return nonEmptyAnswerValueField(rawAnswerRow.answer_value)
}

/** @param {unknown} av */
function nonEmptyAnswerValueField(av) {
  if (av == null) return false
  if (Array.isArray(av)) {
    return av.some(x => {
      const t = x == null ? '' : String(x).trim()
      return t !== '' && t !== NO_EXTRACTED_ANSWER_TEXT
    })
  }
  const s = String(av).trim()
  if (!s || s === NO_EXTRACTED_ANSWER_TEXT) return false
  if (s.startsWith('[')) return parseSerializedListAnswerValue(av).length > 0
  return true
}

/**
 * Multiselect when options are a primitive list (['REST','GraphQL']), API says multi_select,
 * or 2+ structured options when type is not picklist. Conflicts use radios.
 */
export function isReviewMultiSelectMode(q, optionCount, conflictId) {
  if (conflictId) return false
  if (optionCount < 1) return false
  const at = normalizeAnswerType(q)
  if (at === 'picklist') return false
  if (reviewOptionsArePrimitiveList(q)) return true
  if (at === 'multi_select') return true
  return optionCount >= 2
}

export function isReviewPicklistRadiosMode(q, optionCount, conflictId) {
  if (optionCount < 1) return false
  if (conflictId) return true
  const at = normalizeAnswerType(q)
  if (at === 'multi_select') return false
  if (at === 'picklist') return true
  if (reviewOptionsArePrimitiveList(q)) return false
  if (isReviewMultiSelectMode(q, optionCount, false)) return false
  return false
}

/**
 * Same classification as QuestionCard `assistAnswerStructured` (pseudoQ from `apiAnswerType` + display answer).
 * When true, Accept must use `assistSelection` — do not rely on `reviewAnswerOptions(mergedReviewRow)` alone;
 * option lists can differ (e.g. piclist catalog applies with `apiAnswerType` but not with a sparse merged row).
 *
 * @param {Record<string, unknown>} qModel - QuestionCard model from `buildQuestionCardModelFromApiAnswer`
 * @param {Record<string, unknown>} qState - per-question UI state (`editedAnswer`, `status`, `override`, `conflictResolved`)
 */
export function requiresAssistSelectionForAccept(qModel, qState) {
  if (!qModel?.fromApi || !qModel?.apiAnswerType) return false
  if ((qModel.conflicts?.length ?? 0) >= 2 && !qState?.conflictResolved) return false
  if (qState?.status === 'overridden') return false
  const st = qState?.status ?? 'pending'
  const displayAnswer =
    qState?.editedAnswer ||
    (st === 'overridden' && qState?.override ? qState.override : qModel.answer)
  if (displayAnswer == null || String(displayAnswer).trim() === '') return false
  const pseudoQ = {
    question_id: qModel.id,
    answer_type: qModel.apiAnswerType,
    answer_value: displayAnswer,
  }
  const opts = reviewAnswerOptions(pseudoQ)
  const n = opts.length
  if (n < 1) return false
  const showMulti = isReviewMultiSelectMode(pseudoQ, n, false)
  const showPick = isReviewPicklistRadiosMode(pseudoQ, n, false)
  return showMulti || showPick
}

export function isQuestionRequired(q) {
  const r = String(q?.requirement_type ?? q?.requirementType ?? '').trim().toLowerCase()
  if (r === 'required' || r === 'mandatory') return true
  if (q?.is_required === true || q?.required === true) return true
  return false
}

/** Normalize pick/conflict selection: string or single-element array from drafts. */
function pickSelectionString(sel) {
  if (typeof sel === 'string') return sel.trim()
  if (Array.isArray(sel) && sel.length > 0 && sel[0] != null) return String(sel[0]).trim()
  return ''
}

function normalizeRawAnswerForSubmit(raw) {
  if (raw == null) return ''
  if (Array.isArray(raw)) {
    const list = raw.map(x => String(x ?? '').trim()).filter(Boolean)
    return list.length > 0 ? serializeAssistMultiValue(list) : ''
  }
  const text = String(raw).trim()
  if (!text || text === NO_EXTRACTED_ANSWER_TEXT) return ''
  return text
}

function selectionToSubmitAnswerValue(q, sel) {
  if (Array.isArray(sel)) {
    const labels = sel
      .map(v => {
        const sid = String(v ?? '').trim()
        if (!sid) return ''
        const opt = reviewAnswerOptions(q).find(
          o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
        )
        return String(opt?.text ?? sid).trim()
      })
      .filter(Boolean)
    return labels.length > 0 ? serializeAssistMultiValue(labels) : ''
  }
  const sid = String(sel ?? '').trim()
  if (!sid) return ''
  const opt = reviewAnswerOptions(q).find(
    o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
  )
  if (opt?.text != null && String(opt.text).trim() !== '') return String(opt.text).trim()
  const answerRows = Array.isArray(q?.answers) ? q.answers : []
  const answerHit = answerRows.find(a => {
    if (a == null || typeof a !== 'object') return false
    const aid = String(a.answer_id ?? a.id ?? '').trim()
    const av = String(a.answer_value ?? a.value ?? a.text ?? '').trim()
    return aid === sid || av === sid
  })
  if (answerHit) {
    const answerLabel = String(
      answerHit.answer_value ?? answerHit.value ?? answerHit.text ?? answerHit.label ?? '',
    ).trim()
    if (answerLabel) return answerLabel
  }
  return sid
}

function resolveHumanAnswerValueFromId(q, rawRow, answerId) {
  const sid = String(answerId ?? '').trim()
  if (!sid) return ''
  const fromOptions = reviewAnswerOptions(q).find(
    o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
  )
  if (fromOptions?.text != null && String(fromOptions.text).trim() !== '') {
    return String(fromOptions.text).trim()
  }
  const answerRows = Array.isArray(q?.answers) ? q.answers : []
  for (const row of answerRows) {
    if (row == null || typeof row !== 'object') continue
    const rid = String(row.answer_id ?? row.id ?? '').trim()
    const raw = row.answer_value ?? row.value ?? row.text ?? row.label
    const label = raw != null ? String(raw).trim() : ''
    if (rid && rid === sid && label) return label
  }
  if (rawRow && String(rawRow?.answer_id ?? '').trim() === sid) {
    const label = String(rawRow?.answer_value ?? rawRow?.value ?? '').trim()
    if (label) return label
  }
  const conflicts = Array.isArray(rawRow?.conflicts) ? rawRow.conflicts : []
  for (const c of conflicts) {
    const cid = String(c?.answer_id ?? '').trim()
    const label = String(c?.answer_value ?? c?.answer ?? c?.value ?? '').trim()
    if (cid && cid === sid && label) return label
  }
  return ''
}

function sanitizeAnswerValueForWire(q, rawRow, answerId, answerValue) {
  const sid = String(answerId ?? '').trim()
  const raw = answerValue == null ? '' : String(answerValue).trim()
  if (!sid) return raw
  if (!raw || raw === sid) {
    const fallback = resolveHumanAnswerValueFromId(q, rawRow, sid)
    if (fallback && fallback !== sid) return fallback
  }
  return raw
}

/** Only backend-pending rows from GET /answers are eligible for POST updates. */
function shouldSkipSubmitForAnswerStatus(status) {
  return String(status ?? '').trim().toLowerCase() !== 'pending'
}

/** Read `selections[question_id]` whether the record key is string or numeric. */
export function selectionRecordGet(rec, qid) {
  if (rec == null || qid == null) return undefined
  const k = String(qid)
  if (Object.prototype.hasOwnProperty.call(rec, k)) return rec[k]
  if (typeof qid !== 'string' && Object.prototype.hasOwnProperty.call(rec, qid)) return rec[qid]
  return undefined
}

/** @param {Record<string, string|string[]>} apiSelections */
/** @param {Record<string, { status?: string, override?: string, editedAnswer?: string, conflictResolved?: boolean }>} [qState] */
export function validateRequiredReviewQuestions(questions, apiSelections, qState, opts = {}) {
  const errorsByQid = {}
  const rawByQ = new Map(
    (opts.rawAnswerRows || []).map(r => [postMapQidKey(r.question_id), r]).filter(([k]) => k),
  )
  const invalidPlaceholderSet = new Set([
    'no extracted answer available for this question.',
    'no answer given',
    'no answer generated',
    'new answer generated',
    'use edited',
  ])
  const isAcceptedValueValid = value => {
    const v = String(value ?? '').trim()
    if (!v) return false
    const norm = v.toLowerCase().replace(/\s+/g, ' ').replace(/[!?.,;:]+$/g, '')
    return !invalidPlaceholderSet.has(norm)
  }
  for (const q of questions || []) {
    if (!isQuestionRequired(q)) continue
    const qid = q.question_id
    const st = qState?.[qid] || {}
    const rawRow = rawByQ.get(postMapQidKey(qid)) || {}
    const sel = selectionRecordGet(apiSelections, qid)
    const status = String(st.status ?? '').trim().toLowerCase()
    const editedAnswer = String(st.editedAnswer ?? '').trim()
    const override = String(st.override ?? '').trim()
    const selectedAnswer = String(selectionToSubmitAnswerValue(q, sel) ?? '').trim()
    const backendAnswer =
      String(
        selectionToSubmitAnswerValue(q, rawRow?.answer_value) ||
        normalizeRawAnswerForSubmit(rawRow?.answer_value) ||
        normalizeRawAnswerForSubmit(q?.answer_value) ||
        '',
      ).trim()
    const finalAcceptedAnswer = editedAnswer || override || selectedAnswer || backendAnswer || null
    const complete =
      (status === 'accepted' || status === 'overridden') &&
      isAcceptedValueValid(finalAcceptedAnswer)
    console.log('[Section Progress]', {
      qid,
      status: st.status ?? null,
      editedAnswer: st.editedAnswer ?? null,
      override: st.override ?? null,
      selectedAnswer: selectedAnswer || null,
      backendAnswer: backendAnswer || null,
      answerSource: st.answerSource ?? null,
      complete,
    })
    if (!complete) errorsByQid[qid] = 'This answer is required'
  }
  const keys = Object.keys(errorsByQid)
  const hint =
    keys.length === 0
      ? ''
      : keys.length <= 4
        ? ` (${keys.join(', ')})`
        : ` (${keys.length} fields, e.g. ${keys.slice(0, 3).join(', ')}…)`
  return {
    ok: keys.length === 0,
    errorsByQid,
    message: keys.length ? `Please complete all required fields before submitting.${hint}` : '',
  }
}

/**
 * Ensures accepted/overridden rows have a concrete selection for POST /answers (pick, multi, text, or override).
 * Aligns with `buildOpportunityReviewUpdates` + `resolveConflictIdForPost` (conflict rows keep a non-null group id when conflicts exist).
 * @param {{ opportunityId?: string|null, rawAnswerRows?: unknown[] }} [opts]
 */
export function validateReviewSelectionsForSubmit(questions, apiSelections, qState, opts = {}) {
  const opportunityId =
    opts.opportunityId != null && String(opts.opportunityId).trim() !== ''
      ? String(opts.opportunityId).trim()
      : null
  const rawByQ = new Map(
    (opts.rawAnswerRows || []).map(r => [postMapQidKey(r.question_id), r]).filter(([k]) => k),
  )
  const errorsByQid = {}
  const isMeaningfulConflictValue = (raw) => {
    const t = String(raw ?? '').trim()
    if (!t) return false
    const norm = t.toLowerCase().replace(/\s+/g, ' ').replace(/[!?.,;:]+$/g, '')
    if (!norm) return false
    if (norm === 'no answer given') return false
    if (norm === 'no answer generated') return false
    if (norm === 'nothing') return false
    if (norm === 'null') return false
    if (norm.includes('no extracted answer')) return false
    if (norm.includes('new answer generated')) return false
    if (norm === 'use edited') return false
    return true
  }
  const conflictRowHasSubstantiveChoices = (row) => {
    const list = Array.isArray(row?.conflicts) ? row.conflicts : []
    if (list.length === 0) return false
    return list.some(c => isMeaningfulConflictValue(c?.answer_value ?? c?.answer ?? c?.value))
  }

  for (const q of questions || []) {
    const qid = q.question_id
    if (qid == null) continue
    const st = selectionRecordGet(qState, qid)
    if (!st || st.status === 'pending') continue
    // Server-submitted/locked rows should never block submit validation.
    if (st.serverLocked === true) continue

    const rawRowEarly = rawByQ.get(String(qid)) || {}
    if (
      String(rawRowEarly.status ?? '').toLowerCase() === 'active' &&
      st.serverLocked !== false
    ) {
      continue
    }

    if (st.status === 'overridden') {
      const t = String(st.override ?? st.editedAnswer ?? '').trim()
      if (!t) errorsByQid[qid] = 'Override text is required'
      continue
    }

    if (st.status !== 'accepted') continue

    const rawRow = rawByQ.get(postMapQidKey(qid)) || {}
    /**
     * Only treat as a conflict if the **GET /answers row** has a real (non-synthetic) conflict_id
     * AND actual competing answer texts. Rows with only a frontend-inferred conflict_id
     * (e.g. `{oid}:{qid}:conflict`) should not block submission.
     */
    const rawConflictIdStr = rawRow?.conflict_id != null ? String(rawRow.conflict_id).trim() : ''
    const hasRealConflictId =
      rawConflictIdStr !== '' &&
      !isFrontendInferredConflictGroupId(rawConflictIdStr, opportunityId, qid)
    const hasBackendConflict =
      hasRealConflictId &&
      hasExtractedAnswerConflicts(rawRow) &&
      (
        // Only enforce conflict resolution when there are actual competing answer texts.
        conflictRowHasSubstantiveChoices(rawRow) ||
        // If backend gives a conflict_id but no choices, treat as non-blocking metadata.
        false
      )
    const effectiveConflictId = hasBackendConflict
      ? resolveConflictIdForPost(rawRow, q, opportunityId)
      : null

    /**
     * If the user manually entered an answer (answerSource === 'user' and editedAnswer is non-empty),
     * treat it as a valid "Accepted User Response" — no conflict resolution required.
     * Only enforce conflict resolution when there is no user-provided answer.
     */
    const hasValidManualAnswer =
      String(st?.answerSource ?? '').trim().toLowerCase() === 'user' &&
      String(st?.editedAnswer ?? '').trim() !== ''
    if (hasBackendConflict && !st.conflictResolved && !hasValidManualAnswer) {
      errorsByQid[qid] = 'Resolve the conflict before accepting'
      if (import.meta.env.DEV) {
        const rawConflicts = Array.isArray(rawRow?.conflicts) ? rawRow.conflicts : []
        console.info('[Submit Validation: conflict block]', {
          qid,
          qState: {
            status: st?.status ?? null,
            conflictResolved: st?.conflictResolved ?? null,
            serverLocked: st?.serverLocked ?? null,
            answerSource: st?.answerSource ?? null,
            editedAnswer: st?.editedAnswer ?? null,
          },
          rawRow: {
            status: rawRow?.status ?? null,
            conflict_id: rawRow?.conflict_id ?? null,
            conflicts_len: rawConflicts.length,
            answer_id: rawRow?.answer_id ?? null,
            answer_value: rawRow?.answer_value ?? null,
          },
        })
      }
      continue
    }

    const optsList = reviewAnswerOptions(q)
    const n = optsList.length
    const pick = isReviewPicklistRadiosMode(q, n, Boolean(effectiveConflictId))
    const multi = isReviewMultiSelectMode(q, n, Boolean(effectiveConflictId))
    const sel = selectionRecordGet(apiSelections, qid)

    if (multi) {
      let ids = Array.isArray(sel) ? sel.filter(x => x != null && String(x).trim() !== '') : []
      /**
       * Conflict-array rows (conflicts[] present, no group conflict_id) are classified as
       * multi here because conflictId is null and n >= 2. The user resolves them by picking
       * one option (stored as a string in apiSelections) or by entering a manual answer.
       * Both are valid — treat a non-array string sel as a single valid selection.
       */
      if (ids.length === 0 && typeof sel === 'string' && sel.trim() !== '') ids = [sel.trim()]
      /**
       * Also accept a pinned conflict answer id (set when the user resolves the conflict modal)
       * or a manually entered answer (editedAnswer) — both mean the user has provided a response.
       */
      if (ids.length === 0) {
        const caid = String(st?.conflictAnswerId ?? '').trim()
        if (caid) ids = [caid]
      }
      if (ids.length === 0) {
        const editedV = String(st?.editedAnswer ?? '').trim()
        if (editedV) continue
      }
      /**
       * Merged map can be empty after id alignment or key quirks even when GET /answers + review `q`
       * still carry `selected_answer_ids` / list `answer_value` — same fallbacks as
       * {@link mergeApiSelectionsForSubmit}.
       */
      if (ids.length === 0) {
        const pre =
          Array.isArray(rawRow.selected_answer_ids) && rawRow.selected_answer_ids.length
            ? rawRow.selected_answer_ids
            : Array.isArray(q.selected_answer_ids) && q.selected_answer_ids.length
              ? q.selected_answer_ids
              : null
        if (pre) ids = pre.map(x => String(x).trim()).filter(Boolean)
      }
      if (ids.length === 0 && rawRow.answer_value != null) {
        const list =
          typeof rawRow.answer_value === 'string'
            ? parseSerializedListAnswerValue(rawRow.answer_value)
            : Array.isArray(rawRow.answer_value)
              ? rawRow.answer_value.map(x => String(x).trim()).filter(Boolean)
              : []
        if (list.length) ids = list.map(String)
      }
      // Final fallback: a raw backend answer_id counts as a submitted answer
      if (ids.length === 0 && rawRow.answer_id != null && String(rawRow.answer_id).trim() !== '') {
        ids = [String(rawRow.answer_id).trim()]
      }
      if (ids.length === 0) errorsByQid[qid] = 'Choose at least one option'
      continue
    }

    if (pick) {
      let id = pickSelectionString(sel)
      if (!id) {
        if (rawRow.answer_id != null && String(rawRow.answer_id).trim() !== '') {
          id = String(rawRow.answer_id).trim()
        } else if (q.final_answer_id != null && String(q.final_answer_id).trim() !== '') {
          id = String(q.final_answer_id).trim()
        } else if (
          rawRow.answer_value != null &&
          typeof rawRow.answer_value === 'string' &&
          String(rawRow.answer_value).trim() !== ''
        ) {
          id = String(rawRow.answer_value).trim()
        }
      }
      if (!id) {
        /**
         * After Accept (AI source), editedAnswer is reset to ''. Check fallbacks in order:
         * 1. Pinned conflict branch id from resolveConflict
         * 2. Accepted answer value stored at accept time
         * 3. editedAnswer / override text
         * 4. First substantive conflict option id (covers hydration-restored questions)
         */
        const caid = String(st?.conflictAnswerId ?? '').trim()
        if (caid) continue
        const acceptedVal = String(st?.acceptedAnswerValue ?? '').trim()
        if (acceptedVal) continue
        const acceptedText = String(st.editedAnswer ?? st.override ?? '').trim()
        if (acceptedText) continue
        // If this is a conflict row with options, any option is acceptable evidence of resolution
        if (hasBackendConflict) {
          const firstConflictOption = (Array.isArray(rawRow?.conflicts) ? rawRow.conflicts : [])
            .find(c => {
              const val = String(c?.answer_value ?? c?.answer ?? c?.value ?? '').trim()
              return val.length > 0
            })
          if (firstConflictOption) continue
        }
        errorsByQid[qid] = 'Please select an option'
      }
      continue
    }

    const typed = typeof sel === 'string' ? sel.trim() : ''
    const arrOk = Array.isArray(sel) && sel.some(x => x != null && String(x).trim() !== '')
    const ed = String(st.editedAnswer ?? '').trim()
    const hasModel =
      Boolean(q.final_answer_id != null && String(q.final_answer_id).trim() !== '') ||
      (Array.isArray(q.selected_answer_ids) && q.selected_answer_ids.length > 0)
    const preview = String(reviewStaticAnswerPreview(q) || '').trim()
    const rawStr =
      rawRow?.answer_value != null && typeof rawRow.answer_value === 'string'
        ? String(rawRow.answer_value).trim()
        : ''
    const rawTextOk =
      rawStr !== '' &&
      rawStr !== NO_EXTRACTED_ANSWER_TEXT &&
      rawStr !== 'No extracted answer available in payload for this question.'
    if (typed || arrOk || ed || hasModel || preview || rawTextOk) continue
    errorsByQid[qid] = 'No answer to submit'
  }

  const keys = Object.keys(errorsByQid)
  return {
    ok: keys.length === 0,
    errorsByQid,
    message:
      keys.length === 0
        ? ''
        : keys.length <= 3
          ? `Complete every answer before submitting (${keys.join(', ')}).`
          : `Complete every answer before submitting (${keys.length} questions incomplete).`,
  }
}

function isSelectionEmpty(sel, pick, multi, hasConflict) {
  if (multi) {
    /**
     * Assist often stores a single pick as a string UUID while `isReviewMultiSelectMode` is true
     * (2+ catalog options + missing `answer_type`). Treat non-empty string as a real selection.
     */
    if (typeof sel === 'string' && sel.trim() !== '') return false
    return !Array.isArray(sel) || sel.filter(x => x != null && String(x).trim() !== '').length === 0
  }
  if (pick || hasConflict) return typeof sel !== 'string' || sel.trim() === ''
  if (sel == null) return true
  if (typeof sel === 'string') return sel.trim() === ''
  if (Array.isArray(sel)) return sel.filter(Boolean).length === 0
  return true
}

/**
 * When the user clicked Accept but `apiSelections` was never updated, copy from the review model.
 * Conflict rows only backfill after the user resolved the conflict.
 */
function backfillFromAcceptedState(q, out, qState) {
  const qKey = q.question_id
  if (qKey == null) return
  const st = qState?.[qKey]
  if (!st || st.status !== 'accepted') return

  const conflictId = Boolean(q.conflict?.conflict_id)
  const opts = reviewAnswerOptions(q)
  const n = opts.length
  const pick = isReviewPicklistRadiosMode(q, n, conflictId)
  const multi = isReviewMultiSelectMode(q, n, conflictId)
  const sel = out[qKey]

  if (!isSelectionEmpty(sel, pick, multi, conflictId)) return

  if (conflictId) {
    if (!st.conflictResolved) return
    const ed = String(st?.editedAnswer ?? '').trim()
    const opts = reviewAnswerOptions(q)
    if (ed && opts.length) {
      const hit = opts.find(
        o => String(o.text).trim() === ed || String(o.id) === ed || String(o.id).toLowerCase() === ed.toLowerCase(),
      )
      if (hit) {
        out[qKey] = String(hit.id)
        return
      }
      if (looksLikeUuid(ed)) {
        out[qKey] = ed
        return
      }
    }
    /**
     * After Accept with AI source, editedAnswer is reset to ''. Use the explicitly chosen conflict
     * branch id that was pinned in qState during conflict resolution as the primary fallback,
     * then fall through to the question's primary answer, and finally to the first substantive
     * conflict branch so the POST body is never sent empty.
     */
    const caid = String(st?.conflictAnswerId ?? '').trim()
    if (caid) {
      out[qKey] = caid
      return
    }
    const aid =
      q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
        ? String(q.final_answer_id).trim()
        : null
    if (aid) {
      out[qKey] = aid
      return
    }
    // Last resort: first conflict option that has both an id and a meaningful value
    const firstConflictId = (() => {
      for (const o of reviewAnswerOptions(q)) {
        const id = String(o?.id ?? '').trim()
        const txt = String(o?.text ?? '').trim()
        if (id && txt) return id
      }
      return null
    })()
    if (firstConflictId) out[qKey] = firstConflictId
    return
  }
  if (pick) {
    const aid =
      q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
        ? String(q.final_answer_id).trim()
        : null
    if (aid) {
      out[qKey] = aid
      return
    }
    const ed = String(st?.editedAnswer ?? '').trim()
    if (ed) {
      out[qKey] = ed
    }
    return
  }
  if (multi) {
    const pre =
      Array.isArray(q.selected_answer_ids) && q.selected_answer_ids.length ? q.selected_answer_ids : null
    if (pre) out[qKey] = pre.map(String)
    return
  }
  const aid =
    q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
      ? String(q.final_answer_id).trim()
      : null
  if (aid) {
    out[qKey] = aid
    return
  }
  const pv = reviewStaticAnswerPreview(q)
  if (pv) out[qKey] = pv
}

/**
 * Fill missing `apiSelections` from GET /answers rows + review question defaults so POST /answers
 * still runs after "Accept" on plain text or when only the API row had answer_id / answer_value.
 * Then aligns pick / multi-select ids per question via {@link applyPostIdAlignmentToSelections} when
 * `options.questionsCatalog` + `answersRows` yield a non-empty allowed id map.
 * @param {unknown[]} [answersRows] - normalized opportunity answer rows
 * @param {Record<string, { status?: string, conflictResolved?: boolean }>} [qState] - optional UI state for Accept backfill
 * @param {{ questionsCatalog?: unknown[] }} [options]
 */
export function mergeApiSelectionsForSubmit(questions, apiSelections, answersRows, qState, options = {}) {
  const byQ = new Map(
    (answersRows || []).map(a => [postMapQidKey(a.question_id), a]).filter(([k]) => k),
  )
  const out = { ...(apiSelections || {}) }

  for (const q of questions || []) {
    const qKey = q.question_id
    if (qKey == null) continue
    backfillFromAcceptedState(q, out, qState || {})
    const row = byQ.get(postMapQidKey(qKey))
    const conflictId =
      q?.conflict?.conflict_id != null && String(q.conflict.conflict_id).trim() !== ''
        ? String(q.conflict.conflict_id).trim()
        : null
    const opts = reviewAnswerOptions(q)
    const n = opts.length
    const pick = isReviewPicklistRadiosMode(q, n, conflictId)
    const multi = isReviewMultiSelectMode(q, n, conflictId)
    const sel = selectionRecordGet(out, qKey)

    if (!isSelectionEmpty(sel, pick, multi, conflictId)) continue

    if (conflictId) {
      /**
       * For conflict rows where apiSelections is empty, seed from:
       * 1. The pinned conflict branch id from qState (set during resolveConflict)
       * 2. The raw row's primary answer_id
       * 3. The review question's final_answer_id
       * 4. First substantive option from the conflict choices list (last resort)
       */
      const stEntry = qState?.[String(qKey)]
      const caid = String(stEntry?.conflictAnswerId ?? '').trim()
      const aid = caid ||
        (row?.answer_id != null && String(row.answer_id).trim() !== ''
          ? String(row.answer_id).trim()
          : q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
            ? String(q.final_answer_id).trim()
            : (() => {
                for (const o of reviewAnswerOptions(q)) {
                  const id = String(o?.id ?? '').trim()
                  const txt = String(o?.text ?? '').trim()
                  if (id && txt) return id
                }
                return null
              })())
      if (aid) out[qKey] = aid
      continue
    }

    if (multi) {
      const pre =
        Array.isArray(row?.selected_answer_ids) && row.selected_answer_ids.length
          ? row.selected_answer_ids
          : Array.isArray(q.selected_answer_ids) && q.selected_answer_ids.length
            ? q.selected_answer_ids
            : null
      if (pre) {
        out[qKey] = pre.map(String)
        continue
      }
      if (row?.answer_value == null) continue
      const list =
        typeof row.answer_value === 'string'
          ? parseSerializedListAnswerValue(row.answer_value)
          : Array.isArray(row.answer_value)
            ? row.answer_value.map(x => String(x).trim()).filter(Boolean)
            : []
      if (list.length) {
        out[qKey] = list.map(val => {
          const s = String(val).trim()
          if (looksLikeUuid(s)) return s
          return s
        })
      }
      continue
    }

    if (pick) {
      const aid =
        row?.answer_id != null && String(row.answer_id).trim() !== ''
          ? String(row.answer_id).trim()
          : q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
            ? String(q.final_answer_id).trim()
            : null
      if (aid) {
        out[qKey] = aid
        continue
      }
      if (row?.answer_value != null && typeof row.answer_value === 'string' && row.answer_value.trim()) {
        const t = row.answer_value.trim()
        out[qKey] = t
      }
      continue
    }

    const aid =
      row?.answer_id != null && String(row.answer_id).trim() !== ''
        ? String(row.answer_id).trim()
        : q.final_answer_id != null && String(q.final_answer_id).trim() !== ''
          ? String(q.final_answer_id).trim()
          : opts[0]?.id != null
            ? String(opts[0].id)
            : null
    if (aid) out[qKey] = aid
    else if (row?.answer_value != null && typeof row.answer_value === 'string' && row.answer_value.trim()) {
      const t = row.answer_value.trim()
      out[qKey] = t
    }
  }

  return applyPostIdAlignmentToSelections(questions, out, options.questionsCatalog, answersRows)
}

function looksLikeUuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(s || '').trim(),
  )
}

/** Match piclist option text to GET /questions answer rows when counts differ (index alignment is not enough). */
function normAnswerLabelKey(t) {
  return String(t ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
}

/** True when `conflict_id` is the FE-only `{opp}:{qid}:conflict` pattern (not a backend UUID). POST may still send it when the row has `conflicts[]` and the API omitted `conflict_id`. */
export function isFrontendInferredConflictGroupId(id, opportunityId, qid) {
  if (id == null || String(id).trim() === '') return false
  const s = String(id).trim()
  if (looksLikeUuid(s)) return false
  if (opportunityId && qid && s === inferConflictGroupId(String(opportunityId), String(qid))) return true
  return /^[^:]+:[^:]+:conflict$/.test(s)
}

/** Compare backend answer ids; UUIDs compared case-insensitively. */
function sameAnswerId(a, b) {
  if (a == null || b == null) return false
  const sa = String(a).trim()
  const sb = String(b).trim()
  if (!sa || !sb) return false
  if (looksLikeUuid(sa) && looksLikeUuid(sb)) return sa.toLowerCase() === sb.toLowerCase()
  return sa === sb
}

/** GET /answers row has a stored answer id (baseline exists for “override vs new answer” decisions). */
function hasServerBaselineAnswerId(rawRow) {
  if (!rawRow) return false
  return rawRow.answer_id != null && String(rawRow.answer_id).trim() !== ''
}

/**
 * For picklist POST rows, prefer the persisted GET /answers `answer_id` when present — including
 * `is_user_override: true` — so the wire id stays the row’s id; the chosen option goes in `override_value`.
 */
function pickWireAnswerIdForPicklistPost(qid, rawRow, fallbackOptionId, idMaps) {
  if (hasServerBaselineAnswerId(rawRow)) {
    return String(rawRow.answer_id).trim()
  }
  if (fallbackOptionId == null || String(fallbackOptionId).trim() === '') return null
  return coerceSinglePostAnswerId(qid, String(fallbackOptionId).trim(), idMaps)
}

/**
 * True when submitted pick matches GET `answer_id` after POST id coercion (studio id `8` vs backend UUID).
 * Also treats two different UUIDs as equal when they map to the same human label (GET vs catalog-preferred id).
 */
function samePickAnswerIdAsRawRow(q, rawRow, resolvedId, idMaps) {
  if (resolvedId == null || rawRow == null) return false
  const bid =
    rawRow.answer_id != null && String(rawRow.answer_id).trim() !== ''
      ? String(rawRow.answer_id).trim()
      : null
  if (bid == null) return false
  const qid = String(q?.question_id ?? '')
  return pickOptionIdsSemanticallyEqual(q, qid, bid, resolvedId, idMaps)
}

/** Order-insensitive: GET multi-select ids vs submitted ids. */
function sameMultiAnswerIdsAsRawRow(rawRow, resolvedIds) {
  if (rawRow == null || !Array.isArray(resolvedIds) || resolvedIds.length === 0) return false
  let baseIds = []
  if (Array.isArray(rawRow.selected_answer_ids) && rawRow.selected_answer_ids.length) {
    baseIds = rawRow.selected_answer_ids.map(x => String(x).trim()).filter(Boolean)
  } else if (rawRow.answer_id != null && String(rawRow.answer_id).trim() !== '') {
    baseIds = [String(rawRow.answer_id).trim()]
  } else {
    return false
  }
  if (baseIds.length !== resolvedIds.length) return false
  const used = new Set()
  for (const r of resolvedIds.map(x => String(x).trim())) {
    let matched = false
    for (let i = 0; i < baseIds.length; i++) {
      if (used.has(i)) continue
      if (sameAnswerId(r, baseIds[i])) {
        used.add(i)
        matched = true
        break
      }
    }
    if (!matched) return false
  }
  return used.size === baseIds.length
}

/**
 * Option UUIDs embedded in GET `answer_value` list strings (composite row id in `answer_id` is not an option id).
 */
function extractOptionUuidsFromAnswerValueRow(rawRow) {
  if (!rawRow) return []
  if (Array.isArray(rawRow.selected_answer_ids) && rawRow.selected_answer_ids.length) {
    return rawRow.selected_answer_ids.map(x => String(x).trim()).filter(Boolean)
  }
  const av = rawRow.answer_value ?? rawRow.value
  if (typeof av === 'string' && av.trim().startsWith('[')) {
    return parseSerializedListAnswerValue(av)
      .map(x => String(x).trim())
      .filter(x => looksLikeUuid(x))
  }
  if (typeof av === 'string' && av.includes(',')) {
    return av
      .split(/,\s*/)
      .map(x => String(x).trim())
      .filter(x => looksLikeUuid(x))
  }
  return []
}

function multiOptionIdSetsSemanticallyEqual(q, qid, idsA, idsB, idMaps) {
  if (!idsA.length || !idsB.length || idsA.length !== idsB.length) return false
  const used = new Set()
  for (const x of idsA) {
    let matched = false
    for (let i = 0; i < idsB.length; i++) {
      if (used.has(i)) continue
      if (pickOptionIdsSemanticallyEqual(q, qid, x, idsB[i], idMaps)) {
        used.add(i)
        matched = true
        break
      }
    }
    if (!matched) return false
  }
  return used.size === idsB.length
}

/**
 * Turn a UI/API selection (UUID or label) into the canonical `answer_id` for POST — prefer GET /questions ids, not piclist.
 */
function resolveCanonicalAnswerId(q, raw) {
  const c = String(raw ?? '').trim()
  if (!c) return null
  if (looksLikeUuid(c)) return c
  const ro = reviewAnswerOptions(q)
  const byId = ro.find(o => String(o.id) === c)
  if (byId) {
    const id = String(byId.id).trim()
    return looksLikeUuid(id) ? id : null
  }
  const byText = ro.find(o => String(o.text).trim() === c)
  if (byText) {
    const id = String(byText.id).trim()
    return looksLikeUuid(id) ? id : null
  }
  return null
}

/** Map selection string to catalog option `{ id, text }` when possible. */
function resolvePickOption(q, selRaw) {
  const opts = reviewAnswerOptions(q)
  const sel = typeof selRaw === 'string' ? selRaw.trim() : ''
  if (!sel) return { id: null, text: '', opts }
  const byId = opts.find(o => String(o.id) === sel)
  if (byId) return { id: String(byId.id), text: String(byId.text).trim(), opts }
  const byText = opts.find(o => String(o.text).trim() === sel)
  if (byText) return { id: String(byText.id), text: String(byText.text).trim(), opts }
  return { id: null, text: '', opts }
}

/**
 * True when `edited` refers to the same picklist option as `resolvedId` (studio id, label, or UUID).
 * Avoids false `is_user_override` when Accept stores the option id but baseline compares to label text.
 */
function editedMatchesResolvedPick(qid, edited, resolvedId, opts) {
  if (!edited || resolvedId == null) return false
  const e = String(edited).trim()
  const r = String(resolvedId).trim()
  if (!e || !r) return false
  if (sameAnswerId(e, r) || e === r) return true
  for (const o of opts) {
    const oid = String(o.id)
    if (!sameAnswerId(oid, r)) continue
    if (e === oid || e === String(o.text).trim()) return true
  }
  return false
}

function optionById(q, id) {
  const opts = reviewAnswerOptions(q)
  return opts.find(o => sameAnswerId(String(o.id), String(id))) ?? null
}

/** First simple (non–list-string) label on GET /questions `answers[]` for this option id — avoids serialized blobs in `text`. */
function answerCatalogRowLabelForId(q, rid) {
  const r = rid != null ? String(rid).trim() : ''
  if (!r) return ''
  const ansArr = Array.isArray(q?.answers) ? q.answers : []
  const hit = ansArr.find(a => a && sameAnswerId(String(a.answer_id ?? a.id ?? ''), r))
  if (!hit) return ''
  for (const k of ['answer_value', 'value', 'text', 'label']) {
    const v = hit[k]
    if (v == null) continue
    const s = String(v).trim()
    if (!s || s.startsWith('[')) continue
    return s
  }
  return ''
}

/** Display labels for selected answer ids (picklist / multi options). */
function labelsForResolvedIds(q, ids) {
  if (!Array.isArray(ids)) return []
  return ids
    .map(id => {
      const o = optionById(q, id)
      return o ? String(o.text).trim() : String(id).trim()
    })
    .filter(Boolean)
}

/**
 * Split nested python/JSON list blobs (sometimes stored as option `text` on merged rows) into leaf labels.
 * Drops UUID-shaped tokens so `override_value` is only human-readable choices.
 */
function unwrapListStringsToHumanLabels(s, depth = 0) {
  if (depth > 10) return []
  const str = String(s ?? '').trim()
  if (!str) return []
  if (!str.startsWith('[')) {
    return looksLikeUuid(str) ? [] : [str]
  }
  const arr = parseSerializedListAnswerValue(str)
  if (arr.length === 0) return looksLikeUuid(str) ? [] : [str]
  const flat = []
  for (const x of arr) {
    const xs = String(x).trim()
    if (!xs) continue
    if (xs.startsWith('[')) {
      flat.push(...unwrapListStringsToHumanLabels(xs, depth + 1))
    } else if (!looksLikeUuid(xs)) {
      flat.push(xs)
    }
  }
  if (flat.length) return flat
  /** Parsed list contained only UUIDs (or nested blobs) — do not emit the outer string as a “label”. */
  if (str.startsWith('[')) return []
  return looksLikeUuid(str) ? [] : [str]
}

/**
 * Human labels for multi-select `override_value`, one per selected id (same resolution as picklist — piclist / idMaps).
 */
function labelsForMultiOverrideWire(q, resolvedIds, idMaps) {
  if (!Array.isArray(resolvedIds)) return []
  const out = []
  const seen = new Set()
  for (const rid of resolvedIds) {
    const ro = optionById(q, rid)
    const lab = pickHumanLabelForOverride(q, rid, ro, '', idMaps)
    const t = String(lab ?? '').trim()
    if (!t) continue
    /**
     * Some merged option texts come through as serialized lists like:
     * - "['GraphQL', 'gRPC', 'SOAP']"
     * - "[\"TLS 1.3\", \"PGP\"]"
     * Flatten those so `override_value` becomes ["GraphQL","gRPC","SOAP"] (real array of strings),
     * not ["['GraphQL', ...]"].
     */
    const leaves = unwrapListStringsToHumanLabels(t)
    const toks = leaves.length ? leaves : [t]
    for (const tok of toks) {
      const s = String(tok ?? '').trim()
      if (!s) continue
      const k = s.toLowerCase()
      if (seen.has(k)) continue
      seen.add(k)
      out.push(s)
    }
  }
  return out
}

/**
 * Human labels for multi `override_value` — never bare option UUIDs (fallback when {@link labelsForMultiOverrideWire} is empty).
 */
function multiOverrideLabelsForWire(q, resolvedIds, idMaps) {
  const from = labelsForMultiOverrideWire(q, resolvedIds, idMaps)
  if (from.length > 0) return from
  const qid = String(q?.question_id ?? '')
  const out = []
  for (const id of resolvedIds || []) {
    const lab = String(pickHumanLabelForOverride(q, id, optionById(q, id), '', idMaps) ?? '').trim()
    if (lab && !looksLikeUuid(lab)) out.push(lab)
  }
  if (out.length > 0) return out
  const m = idMaps?.get(qid)
  for (const id of resolvedIds || []) {
    const lab = m?.idToLabel?.get(String(id).trim())
    if (lab && String(lab).trim() && !looksLikeUuid(String(lab))) out.push(String(lab).trim())
  }
  return out
}

function normalizeMultiLabelTokensForCompare(tokens) {
  if (!Array.isArray(tokens)) return []
  const out = []
  const seen = new Set()
  for (const tok of tokens) {
    for (const leaf of unwrapListStringsToHumanLabels(String(tok))) {
      const t = String(leaf).trim()
      if (!t) continue
      const k = t.toLowerCase()
      if (seen.has(k)) continue
      seen.add(k)
      out.push(t)
    }
  }
  return out
}

function baselinePickLabel(q, rawRow) {
  if (!rawRow) return ''
  const qid = String(q?.question_id ?? '')
  const av = rawRow.answer_value ?? rawRow.value
  if (av != null && String(av).trim() !== '' && !String(av).trim().startsWith('[')) {
    const s = String(av).trim()
    /**
     * GET /answers often stores piclist studio index in `answer_value` ("1","5") while the UI compares
     * human labels ("Multi-tenant"). Map digits → `answer_value` / `option_value` from the piclist.
     */
    if (/^\d+$/.test(s)) {
      const pr = getPiclistAnswerRowsForQuestion(qid).find(
        r => String(r.answer_id) === s || String(r.answer_id) === String(Number(s)),
      )
      if (pr && String(pr.answer_value ?? '').trim()) return String(pr.answer_value).trim()
      const studio = getPiclistStudioRowsForQuestion(qid).find(r => String(r.id) === s)
      if (studio && String(studio.option_value ?? '').trim()) return String(studio.option_value).trim()
    }
    return s
  }
  const bid =
    rawRow.answer_id != null && String(rawRow.answer_id).trim() !== '' ? String(rawRow.answer_id).trim() : null
  if (!bid) return ''
  const o = optionById(q, bid)
  if (o) return String(o.text).trim()
  const ansArr = Array.isArray(q?.answers) ? q.answers : []
  const hit = ansArr.find(a => a && sameAnswerId(String(a.answer_id ?? a.id ?? ''), bid))
  if (hit) {
    const v = hit.answer_value ?? hit.value ?? hit.text
    if (v != null && String(v).trim() && !String(v).trim().startsWith('[')) return String(v).trim()
  }
  for (const pr of getPiclistAnswerRowsForQuestion(qid)) {
    const canon = String(pr.answer_id ?? '').trim()
    if (!canon) continue
    if (sameAnswerId(canon, bid)) {
      const human = String(pr.answer_value ?? '').trim()
      if (human) return human
    }
  }
  return ''
}

/** True when current picklist selection differs from GET /answers baseline (by id or label). */
function pickSelectionChangedFromBaseline(q, rawRow, resolvedId, resolvedOpt, idMaps) {
  if (resolvedId == null) return true
  const bid =
    rawRow?.answer_id != null && String(rawRow.answer_id).trim() !== '' ? String(rawRow.answer_id).trim() : null
  const qid = String(q?.question_id ?? '')
  if (bid != null && idMaps && pickOptionIdsSemanticallyEqual(q, qid, bid, resolvedId, idMaps)) return false
  const ro = resolvedOpt ?? optionById(q, resolvedId)
  let curLabel = ro ? String(ro.text).trim() : ''
  /**
   * POST alignment may use a catalog UUID that `reviewAnswerOptions` did not merge (e.g. preferred id
   * from `idMaps` only). `optionById` then misses → empty label → false “changed”. Resolve like pickHumanLabelForOverride.
   */
  if (!curLabel && idMaps) {
    curLabel = String(pickHumanLabelForOverride(q, resolvedId, ro ?? null, '', idMaps) ?? '').trim()
  }
  let baseLabel = baselinePickLabel(q, rawRow)
  if (!baseLabel && bid && idMaps) {
    baseLabel = String(pickHumanLabelForOverride(q, bid, optionById(q, bid), '', idMaps) ?? '').trim()
  }
  if (bid != null && sameAnswerId(String(resolvedId), bid)) return false
  if (baseLabel !== '' && curLabel !== '' && baseLabel.toLowerCase() === curLabel.toLowerCase()) return false
  /**
   * Same option, different id namespaces (GET row id vs catalog option id): baselinePickLabel / `ro.text`
   * can both be empty while `pickHumanLabelForOverride` still resolves the same human label.
   */
  if (bid != null && idMaps) {
    const la = String(pickHumanLabelForOverride(q, resolvedId, ro ?? null, '', idMaps) ?? '').trim().toLowerCase()
    const lb = String(pickHumanLabelForOverride(q, bid, optionById(q, bid), '', idMaps) ?? '').trim().toLowerCase()
    if (la !== '' && lb !== '' && la === lb) return false
  }
  return true
}

/**
 * Composite single-UUID picklists: one wire `answer_id` for every option; only send `override_value`
 * when there is no GET baseline yet or the chosen label differs from GET (unchanged → plain `answer_id`).
 */
function shouldCompositePicklistSendOverrideLabel(q, rawRow, resolvedId, resolvedOpt, idMaps) {
  if (!hasServerBaselineAnswerId(rawRow)) return true
  return pickSelectionChangedFromBaseline(q, rawRow, resolvedId, resolvedOpt, idMaps)
}

/**
 * User override for pick only when GET had a baseline answer id, submitted id ≠ GET, and label/id delta says “changed”.
 * No server `answer_id` → first-time answer (e.g. NO_ANSWER placeholder) → not a baseline “override”.
 */
function shouldSendPickUserOverrideForBaselineDelta(q, rawRow, resolvedId, resolvedOpt, idMaps) {
  if (!hasServerBaselineAnswerId(rawRow)) return false
  /** Composite: same wire id for every option — compare labels only (samePickAnswerIdAsRawRow is always true). */
  if (isCompositePicklistSingleBackendId(q, rawRow, idMaps)) {
    return pickSelectionChangedFromBaseline(q, rawRow, resolvedId, resolvedOpt, idMaps)
  }
  if (samePickAnswerIdAsRawRow(q, rawRow, resolvedId, idMaps)) return false
  return pickSelectionChangedFromBaseline(q, rawRow, resolvedId, resolvedOpt, idMaps)
}

/**
 * Some picklists have a single backend `answer_id` for the whole question (composite row),
 * while the chosen option lives in `override_value` / answer_value. For these, always send
 * the selected option label as `override_value` (Vertical/Horizontal/None) and keep `answer_id` stable.
 */
function isCompositePicklistSingleBackendId(q, rawRow, idMaps) {
  const qid = String(q?.question_id ?? '')
  if (!qid) return false
  const opts = getPiclistAnswerRowsForQuestion(qid)
  if (!opts || opts.length <= 1) return false
  const m = idMaps?.get(qid)
  if (!m || m.allowed.size === 0) return false
  const allowedUuids = [...m.allowed].filter(a => looksLikeUuid(a))
  if (allowedUuids.length !== 1) return false
  const av = rawRow?.answer_value ?? rawRow?.value
  if (av != null && String(av).trim() !== '' && !String(av).trim().startsWith('[')) return false
  return true
}

/**
 * Composite multi-select: backend uses one UUID for the whole question, selected options live in answer_value/override_value.
 * For these, POST one row with stable `answer_id` + `override_value: ["A","B"]`.
 */
function isCompositeMultiSelectSingleBackendId(q, rawRow, idMaps) {
  const qid = String(q?.question_id ?? '')
  if (!qid) return false
  if (normalizeAnswerType(q) !== 'multi_select') return false
  const opts = getPiclistAnswerRowsForQuestion(qid)
  if (!opts || opts.length <= 1) return false
  const m = idMaps?.get(qid)
  if (!m || m.allowed.size === 0) return false
  const allowedUuids = [...m.allowed].filter(a => looksLikeUuid(a))
  if (allowedUuids.length !== 1) return false
  /** If GET already has a structured list string/value, this is the composite style row. */
  const av = rawRow?.answer_value ?? rawRow?.value
  if (av != null && String(av).trim() !== '' && String(av).trim().startsWith('[')) return true
  /** Also treat null/empty as composite when catalog indicates single backend id. */
  if (av == null || String(av).trim() === '') return true
  return false
}

/**
 * Prefer human label (Horizontal) over studio id text ("8") for `override_value` when piclist/API merge left numeric display.
 * Uses POST id maps + piclist rows so studio `8` ↔ backend UUID both resolve to the same `option_value`.
 */
function pickHumanLabelForOverride(q, resolvedId, ro, selFallback, idMaps) {
  const rid = resolvedId != null ? String(resolvedId).trim() : ''
  if (!rid) return String(selFallback ?? '').trim()
  const qid = String(q?.question_id ?? '')

  /** Direct studio id: always map to the option_value label when possible. */
  if (/^\d+$/.test(rid)) {
    const pr = getPiclistAnswerRowsForQuestion(qid).find(r => String(r.answer_id) === rid)
    if (pr && String(pr.answer_value ?? '').trim()) return String(pr.answer_value).trim()
    const rows = getPiclistStudioRowsForQuestion(qid)
    const studio = rows.find(r => String(r.id) === rid)
    if (studio && String(studio.option_value ?? '').trim()) return String(studio.option_value).trim()
  }

  const m = idMaps?.get(qid)
  const labFromMap = m?.idToLabel?.get(rid)
  if (labFromMap && String(labFromMap).trim()) {
    const L = String(labFromMap).trim()
    if (!/^\d+$/.test(L) && !looksLikeUuid(L)) return L
    if (looksLikeUuid(L)) {
      const cat = answerCatalogRowLabelForId(q, rid)
      if (cat) return cat
    }
  }

  /** Piclist: studio id coerces to same wire UUID as selected option → use human `answer_value`. */
  const plistRows = getPiclistAnswerRowsForQuestion(qid)
  for (const pr of plistRows) {
    const sid = String(pr.answer_id ?? '').trim()
    if (!sid) continue
    const canon = coerceSinglePostAnswerId(qid, sid, idMaps)
    if (sameAnswerId(String(canon), rid)) {
      const human = String(pr.answer_value ?? '').trim()
      if (human) return human
    }
  }

  const rawText = ro ? String(ro.text).trim() : ''
  const ansArr = Array.isArray(q?.answers) ? q.answers : []
  const hit = ansArr.find(a => a && sameAnswerId(String(a.answer_id ?? a.id ?? ''), rid))
  if (hit) {
    const v = hit.answer_value ?? hit.value ?? hit.text
    if (v != null && String(v).trim() && !String(v).trim().startsWith('[')) {
      return String(v).trim()
    }
  }
  const pv = Array.isArray(q?.option_values) ? q.option_values : []
  const idx = ansArr.findIndex(a => a && sameAnswerId(String(a.answer_id ?? a.id ?? ''), rid))
  if (idx >= 0 && idx < pv.length && String(pv[idx]).trim()) return String(pv[idx]).trim()
  if (/^\d+$/.test(rawText)) {
    const rows = getPiclistStudioRowsForQuestion(String(q?.question_id ?? ''))
    const studio = rows.find(r => String(r.id) === rawText)
    if (studio && String(studio.option_value ?? '').trim()) return String(studio.option_value).trim()
  }
  return rawText || String(selFallback ?? '').trim()
}

/**
 * GET /answers may store one backend UUID while the merged UI selection uses another UUID for the same
 * option (e.g. QID-022: `2d255d12…` vs preferred `f627353e…` for “Mutual”). Coercion alone can miss that.
 */
function pickOptionIdsSemanticallyEqual(q, qid, idA, idB, idMaps) {
  if (!idMaps || idA == null || idB == null) return false
  const a = String(idA).trim()
  const b = String(idB).trim()
  if (!a || !b) return false
  const ca = coerceSinglePostAnswerId(qid, a, idMaps)
  const cb = coerceSinglePostAnswerId(qid, b, idMaps)
  if (sameAnswerId(String(ca), String(cb))) return true
  const la = String(pickHumanLabelForOverride(q, a, null, '', idMaps) ?? '').trim().toLowerCase()
  const lb = String(pickHumanLabelForOverride(q, b, null, '', idMaps) ?? '').trim().toLowerCase()
  return la !== '' && lb !== '' && la === lb
}

function baselineMultiLabels(q, rawRow, idMaps) {
  if (!rawRow) return []
  const av = rawRow.answer_value ?? rawRow.value
  if (typeof av === 'string' && av.trim() !== '') {
    const trimmed = av.trim()
    const rawTokens = trimmed.startsWith('[')
      ? parseSerializedListAnswerValue(trimmed).map(x => String(x).trim()).filter(Boolean)
      : trimmed.includes(',')
        ? trimmed.split(/,\s*/).map(x => String(x).trim()).filter(Boolean)
        : []
    if (rawTokens.length > 0) {
      return rawTokens.map(tok => {
        const mapped = String(
          pickHumanLabelForOverride(q, tok, optionById(q, tok), tok, idMaps) ?? tok,
        ).trim()
        return mapped || String(tok).trim()
      }).filter(Boolean)
    }
  }
  if (typeof av === 'string' && av.trim().startsWith('[')) {
    return parseSerializedListAnswerValue(av).map(x => String(x).trim()).filter(Boolean)
  }
  if (Array.isArray(av)) return av.map(x => String(x).trim()).filter(Boolean)
  if (Array.isArray(rawRow.selected_answer_ids) && rawRow.selected_answer_ids.length) {
    return labelsForResolvedIds(q, rawRow.selected_answer_ids)
  }
  if (rawRow.answer_id != null && String(rawRow.answer_id).trim() !== '') {
    return labelsForResolvedIds(q, [String(rawRow.answer_id).trim()])
  }
  return []
}

function sortedLabelKey(labels) {
  return [...labels].map(l => l.toLowerCase()).sort().join('\0')
}

/** True when multi-select labels differ from GET /answers baseline (order-insensitive). */
function multiSelectionChangedFromBaseline(q, rawRow, resolvedIds, idMaps) {
  const qid = String(q?.question_id ?? '')
  const bid = extractOptionUuidsFromAnswerValueRow(rawRow)
  const rid = (resolvedIds || []).map(x => String(x).trim()).filter(Boolean)
  if (bid.length && rid.length && multiOptionIdSetsSemanticallyEqual(q, qid, bid, rid, idMaps)) {
    return false
  }
  const a = sortedLabelKey(normalizeMultiLabelTokensForCompare(baselineMultiLabels(q, rawRow, idMaps)))
  const b = sortedLabelKey(multiOverrideLabelsForWire(q, resolvedIds, idMaps))
  return a !== b
}

/** Stable order for aligning studio piclist rows with GET /questions answer rows. */
function catalogAnswersSorted(q) {
  const rows = q?.answers
  if (!Array.isArray(rows)) return []
  const copy = [...rows]
  copy.sort((a, b) => {
    const sa = Number(a?.sort_order ?? a?.sortOrder ?? 0)
    const sb = Number(b?.sort_order ?? b?.sortOrder ?? 0)
    if (Number.isFinite(sa) && Number.isFinite(sb) && sa !== sb) return sa - sb
    return 0
  })
  return copy
}

/**
 * Collect ids + labels from GET /questions and GET /answers so POST can remap piclist/studio ids to backend UUIDs.
 * @param {unknown[]|null|undefined} questionsCatalog
 * @param {unknown[]} rawAnswerRows
 * @returns {Map<string, { allowed: Set<string>, idToLabel: Map<string, string>, labelToPreferredId: Map<string, string>, studioToCanonical: Map<string, string> }>}
 */
function buildPostAnswerIdMaps(questionsCatalog, rawAnswerRows) {
  const byQ = new Map()

  function ensure(qid) {
    const k = postMapQidKey(qid)
    if (!k) return null
    if (!byQ.has(k)) {
      byQ.set(k, {
        allowed: new Set(),
        idToLabel: new Map(),
        labelToPreferredId: new Map(),
        studioToCanonical: new Map(),
      })
    }
    return byQ.get(k)
  }

  function addPair(qid, id, label) {
    if (id == null || String(id).trim() === '') return
    const canonicalId = String(id).trim()
    if (!looksLikeUuid(canonicalId)) return
    const m = ensure(qid)
    if (!m) return
    const l = label != null ? String(label).trim() : ''
    m.allowed.add(canonicalId)
    if (l && !m.idToLabel.has(canonicalId)) m.idToLabel.set(canonicalId, l)
  }

  for (const q of questionsCatalog || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const fa = q?.final_answer_id ?? q?.finalAnswerId
    if (fa != null && String(fa).trim() !== '') addPair(qid, fa, null)
    const rows = q?.answers
    if (Array.isArray(rows)) {
      for (const a of rows) {
        const id = a?.answer_id ?? a?.id
        const lab = a?.answer_value ?? a?.value ?? a?.text ?? a?.label ?? a?.option_value
        addPair(qid, id, lab)
      }
    }
  }

  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    addPair(qid, row.answer_id, row.answer_value ?? row.value)
    for (const c of row.conflicts || []) {
      addPair(qid, c.answer_id, c.answer_value ?? c.value)
    }
    for (const sid of row.selected_answer_ids || []) {
      addPair(qid, sid, null)
    }
    // Include all merged catalog answer options so that any selected option
    // (not just the currently stored one) can be coerced to its backend UUID.
    for (const optKey of ROW_OPTION_KEYS) {
      const opts = row[optKey]
      if (!Array.isArray(opts) || opts.length === 0) continue
      for (const a of opts) {
        if (a == null || typeof a !== 'object') continue
        const id = a.answer_id ?? a.id
        const lab = a.answer_value ?? a.value ?? a.text ?? a.label ?? a.option_value
        addPair(qid, id, lab)
      }
    }
  }

  /**
   * Multi-select rows often expose only one `answer_id` on the row while each chosen option has its own UUID.
   * Parse `answer_value` list strings (e.g. `['REST','GraphQL']`) and register every option id from GET /questions
   * and from merged row option arrays so POST alignment does not drop valid option UUIDs.
   */
  function labelsFromMultiAnswerRow(row) {
    const av = row?.answer_value ?? row?.value
    if (av == null) return []
    if (Array.isArray(av)) return av.map(x => String(x).trim()).filter(Boolean)
    if (typeof av === 'string' && av.trim().startsWith('[')) return parseSerializedListAnswerValue(av)
    return []
  }

  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    const at = String(row.answer_type ?? row.answerType ?? '')
      .toLowerCase()
      .replace(/[\s-]+/g, '_')
    if (!at.includes('multi')) continue
    const labels = labelsFromMultiAnswerRow(row)
    if (!labels.length) continue
    const qCat = (questionsCatalog || []).find(q => String(q?.question_id) === String(qid))
    const catRows = qCat?.answers
    if (Array.isArray(catRows)) {
      for (const t of labels) {
        const raw = String(t).trim()
        if (!raw) continue
        if (looksLikeUuid(raw)) {
          addPair(qid, raw, null)
          continue
        }
        const tl = raw.toLowerCase()
        for (const a of catRows) {
          if (a == null || typeof a !== 'object') continue
          const lab = String(a.answer_value ?? a.value ?? a.text ?? '').trim().toLowerCase()
          const id = a.answer_id ?? a.id
          if (lab && tl === lab && id != null && String(id).trim() !== '') addPair(qid, id, lab)
        }
      }
    }
    for (const optKey of ROW_OPTION_KEYS) {
      const opts = row[optKey]
      if (!Array.isArray(opts)) continue
      for (const t of labels) {
        const raw = String(t).trim()
        if (!raw) continue
        if (looksLikeUuid(raw)) {
          addPair(qid, raw, null)
          continue
        }
        const tl = raw.toLowerCase()
        for (const a of opts) {
          if (a == null || typeof a !== 'object') continue
          const lab = String(a.answer_value ?? a.value ?? a.text ?? '').trim().toLowerCase()
          const id = a.answer_id ?? a.id
          if (lab && tl === lab && id != null && String(id).trim() !== '') addPair(qid, id, lab)
        }
      }
    }
  }

  /**
   * GET /answers often stores the picklist token in `value` / `answer_value` as a studio index ("1","5",…)
   * while `answer_id` is the backend UUID. Map those digits → row UUID so coerce() can resolve selections.
   */
  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    const m = ensure(qid)
    const mapDigits = (aid, rawVal) => {
      if (aid == null || String(aid).trim() === '') return
      const a = String(aid).trim()
      if (!looksLikeUuid(a)) return
      if (rawVal == null) return
      const vs = String(rawVal).trim()
      if (!/^\d+$/.test(vs)) return
      m.studioToCanonical.set(vs, a)
    }
    mapDigits(row.answer_id, row.answer_value ?? row.value)
    for (const c of row.conflicts || []) {
      mapDigits(c.answer_id, c.answer_value ?? c.value)
    }
  }

  for (const [, m] of byQ) {
    for (const [id, lab] of m.idToLabel) {
      if (!lab) continue
      const key = lab.toLowerCase()
      const cur = m.labelToPreferredId.get(key)
      if (!cur) {
        m.labelToPreferredId.set(key, id)
      } else if (looksLikeUuid(id) && !looksLikeUuid(cur)) {
        m.labelToPreferredId.set(key, id)
      }
    }
  }

  /** Fuzzy keys so "TLS 1.3" ↔ "TLS1.3" align with catalog labels. */
  for (const [, m] of byQ) {
    for (const [key, pref] of [...m.labelToPreferredId.entries()]) {
      const nk = key.replace(/[^a-z0-9]+/g, '')
      if (nk && nk !== key && !m.labelToPreferredId.has(nk)) {
        m.labelToPreferredId.set(nk, pref)
      }
    }
  }

  /**
   * Prefer GET /answers `answer_id` for a given display value so POST matches persisted ids when catalog
   * and row disagree on UUID for the same label.
   */
  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    const m = ensure(qid)
    const prefer = (aid, lab) => {
      if (aid == null || String(aid).trim() === '') return
      const a = String(aid).trim()
      if (!looksLikeUuid(a) || !m.allowed.has(a)) return
      if (lab == null || String(lab).trim() === '') return
      const key = String(lab).trim().toLowerCase()
      m.labelToPreferredId.set(key, a)
      const nk = key.replace(/[^a-z0-9]+/g, '')
      if (nk && nk !== key) m.labelToPreferredId.set(nk, a)
    }
    prefer(row.answer_id, row.answer_value ?? row.value)
    for (const c of row.conflicts || []) {
      prefer(c.answer_id, c.answer_value ?? c.value)
    }
  }

  /**
   * Studio piclist uses numeric ids (e.g. "11"); GET /questions uses UUIDs. When option_value does not
   * exactly match catalog answer_value, align by sort order / index (first N studio options ↔ first N catalog answers).
   */
  for (const q of questionsCatalog || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = postMapQidKey(qid)
    const m = ensure(k)
    if (!m) continue
    const plist = getPiclistAnswerRowsForQuestion(k)
    const catRows = catalogAnswersSorted(q)
    const n = Math.min(plist.length, catRows.length)
    for (let i = 0; i < n; i++) {
      const sid = String(plist[i].answer_id ?? '').trim()
      const cid = catRows[i]?.answer_id ?? catRows[i]?.id
      if (!sid || cid == null || String(cid).trim() === '') continue
      m.studioToCanonical.set(sid, String(cid).trim())
    }
  }

  /**
   * When GET /questions returns fewer `answers[]` than piclist rows, index-only mapping leaves numeric
   * studio ids (e.g. "11", "12") unmapped. Second pass: match piclist `answer_value` to catalog labels.
   */
  for (const q of questionsCatalog || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = postMapQidKey(qid)
    const m = ensure(k)
    if (!m) continue
    const plist = getPiclistAnswerRowsForQuestion(k)
    const catRows = catalogAnswersSorted(q)
    if (!plist.length || !catRows.length) continue

    const labelToCanon = new Map()
    for (const cr of catRows) {
      const cid = cr?.answer_id ?? cr?.id
      if (cid == null || String(cid).trim() === '') continue
      const canon = String(cid).trim()
      for (const label of [cr?.answer_value, cr?.text, cr?.label, cr?.option_value]) {
        if (label == null || String(label).trim() === '') continue
        const key = normAnswerLabelKey(label)
        if (key && !labelToCanon.has(key)) labelToCanon.set(key, canon)
      }
    }
    for (const pr of plist) {
      const sid = String(pr.answer_id ?? '').trim()
      if (!sid) continue
      const pv = String(pr.answer_value ?? '').trim()
      if (!pv) continue
      const key = normAnswerLabelKey(pv)
      if (!key) continue
      const canon = labelToCanon.get(key)
      if (canon) m.studioToCanonical.set(sid, canon)
    }
  }

  /** Every canonical UUID we can reach from studio ids must count as allowed for coercion + validation. */
  for (const [, m] of byQ) {
    for (const cid of m.studioToCanonical.values()) {
      if (cid) m.allowed.add(cid)
    }
  }
  /** Map studio piclist id → GET row UUID when option text matches the stored answer (overrides index-only mapping). */
  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    const k = String(qid)
    const m = ensure(k)
    const aid = row.answer_id != null ? String(row.answer_id).trim() : ''
    if (!aid || !looksLikeUuid(aid)) continue
    const rl = String(row.answer_value ?? row.value ?? '').trim().toLowerCase()
    if (!rl) continue
    for (const pr of getPiclistAnswerRowsForQuestion(k)) {
      const sid = String(pr.answer_id ?? '').trim()
      if (!sid) continue
      const tl = String(pr.answer_value ?? '').trim().toLowerCase()
      if (tl && tl === rl) m.studioToCanonical.set(sid, aid)
    }
  }

  /**
   * When multi-select / conflict values are list strings (e.g. "['AES-256', 'TLS 1.3']"), map each
   * human label to the studio piclist id, then to the backend UUID for that row or conflict option.
   */
  function mapAnswerValueLabelsToStudioIds(qid, canonicalUuid, rawValue) {
    if (canonicalUuid == null || String(canonicalUuid).trim() === '') return
    const canon = String(canonicalUuid).trim()
    const m = ensure(qid)
    const labels = parseSerializedListAnswerValue(rawValue)
    for (const t of labels) {
      const label = String(t).trim()
      if (!label) continue
      if (looksLikeUuid(label)) continue
      const pid = matchPiclistValueToAnswerId(qid, label)
      if (pid) {
        const sid = String(pid)
        if (!m.studioToCanonical.has(sid)) m.studioToCanonical.set(sid, canon)
      }
    }
  }

  for (const row of rawAnswerRows || []) {
    const qid = row?.question_id
    if (qid == null) continue
    mapAnswerValueLabelsToStudioIds(qid, row.answer_id, row.answer_value)
    for (const c of row.conflicts || []) {
      mapAnswerValueLabelsToStudioIds(qid, c.answer_id, c.answer_value)
    }
  }

  for (const q of questionsCatalog || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const rows = q?.answers
    if (!Array.isArray(rows)) continue
    for (const a of rows) {
      const id = a?.answer_id ?? a?.id
      mapAnswerValueLabelsToStudioIds(qid, id, a?.answer_value ?? a?.value)
    }
  }

  /** Single composite GET /questions row + full option_values + studio piclist: fill any unmapped ids. */
  for (const q of questionsCatalog || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = String(qid)
    const m = ensure(k)
    const plist = getPiclistAnswerRowsForQuestion(k)
    const catRows = catalogAnswersSorted(q)
    const optVals = q.option_values ?? q.optionValues
    if (!Array.isArray(optVals) || optVals.length !== plist.length || catRows.length !== 1) continue
    const sole = catRows[0]?.answer_id ?? catRows[0]?.id
    if (sole == null || String(sole).trim() === '') continue
    const cid = String(sole).trim()
    for (const pr of plist) {
      const sid = String(pr.answer_id ?? '').trim()
      if (!sid || m.studioToCanonical.has(sid)) continue
      m.studioToCanonical.set(sid, cid)
    }
  }

  return byQ
}

/**
 * @param {string} qid
 * @param {unknown} value
 * @param {ReturnType<typeof buildPostAnswerIdMaps>} byQ
 */
function coercePostAnswerIdField(qid, value, byQ) {
  if (value === null) return null
  if (value === undefined) return undefined
  if (Array.isArray(value)) {
    return value
      .map(v => coerceSinglePostAnswerId(qid, v, byQ))
      .filter(x => x !== undefined && x !== null && x !== '')
  }
  return coerceSinglePostAnswerId(qid, value, byQ)
}

function coerceSinglePostAnswerId(qid, raw, byQ) {
  const m = byQ.get(postMapQidKey(qid))
  if (!m) {
    const only = String(raw).trim()
    return looksLikeUuid(only) ? only : null
  }
  const s = String(raw).trim()
  if (!s) return s
  if (s === NO_EXTRACTED_ANSWER_TEXT) return null
  if (m.allowed.has(s) && looksLikeUuid(s)) return s
  for (const a of m.allowed) {
    if (sameAnswerId(a, s) && looksLikeUuid(a)) return a
  }
  const labFromId = m.idToLabel.get(s)
  if (labFromId) {
    const ll = labFromId.toLowerCase()
    let pref = m.labelToPreferredId.get(ll)
    if (!pref) {
      const nk = ll.replace(/[^a-z0-9]+/g, '')
      if (nk) pref = m.labelToPreferredId.get(nk)
    }
    if (pref && m.allowed.has(pref) && looksLikeUuid(pref)) return pref
  }
  /** Match free-text selection to catalog label (same option, different id namespace). */
  const sl = s.toLowerCase()
  let prefByLabel = m.labelToPreferredId.get(sl)
  if (!prefByLabel && sl) {
    const nks = sl.replace(/[^a-z0-9]+/g, '')
    if (nks) prefByLabel = m.labelToPreferredId.get(nks)
  }
  if (prefByLabel && m.allowed.has(prefByLabel) && looksLikeUuid(prefByLabel)) return prefByLabel
  for (const aid of m.allowed) {
    const lab = m.idToLabel.get(aid)
    if (lab && lab.toLowerCase() === sl && looksLikeUuid(aid)) return aid
  }
  /** Match when UI stored display text but catalog uses slightly different wording/spacing. */
  const sNorm = normAnswerLabelKey(s)
  if (sNorm) {
    for (const aid of m.allowed) {
      const lab = m.idToLabel.get(aid)
      if (!lab) continue
      if (normAnswerLabelKey(lab) === sNorm && looksLikeUuid(aid)) return aid
    }
  }
  for (const aid of m.allowed) {
    if (sameAnswerId(aid, s) && looksLikeUuid(aid)) return aid
  }
  if (import.meta.env.DEV) {
    const key = `${qid}:${s}`
    if (!__devUnmappedPostAnswerIds.has(key)) {
      __devUnmappedPostAnswerIds.add(key)
      console.warn(`[POST /answers] Unmapped answer_id for ${qid}: "${s}". Allowed:`, [...m.allowed])
    }
  }
  return null
}

/**
 * After coercion, prefer the **persisted** GET /answers `answer_id` when it refers to the same option.
 * Otherwise `labelToPreferredId` / catalog merges can swap UUIDs and the POST body looks “random” vs GET.
 * @param {string} qid
 * @param {unknown} coercedVal - output of {@link coercePostAnswerIdField}
 * @param {ReturnType<typeof buildPostAnswerIdMaps>} idMaps
 * @param {Record<string, unknown>|null|undefined} rawRow
 */
function preferWireAnswerIdFromGetRow(qid, coercedVal, idMaps, rawRow) {
  if (!rawRow || rawRow.answer_id == null || String(rawRow.answer_id).trim() === '') return coercedVal
  if (Array.isArray(coercedVal)) return coercedVal
  const cs = String(coercedVal ?? '').trim()
  if (!cs) return coercedVal
  const gRaw = String(rawRow.answer_id).trim()
  const gCoerced = coerceSinglePostAnswerId(qid, gRaw, idMaps)
  if (sameAnswerId(String(gCoerced), cs)) return gRaw
  return coercedVal
}

function finalizePostUpdatesAnswerIds(updates, idMaps, rawByQ) {
  return updates.map(u => {
    const qid = String(u.q_id ?? '')
    const raw = rawByQ?.get(qid)
    const next = { ...u }
    const useExactGetAnswerId = raw && raw.answer_id != null && String(raw.answer_id).trim() !== ''
    if (Object.prototype.hasOwnProperty.call(u, 'answer_id')) {
      if (useExactGetAnswerId) {
        next.answer_id = String(raw.answer_id).trim()
      } else {
        const coerced = coercePostAnswerIdField(qid, u.answer_id, idMaps)
        next.answer_id = raw ? preferWireAnswerIdFromGetRow(qid, coerced, idMaps, raw) : coerced
      }
    }
    if (Object.prototype.hasOwnProperty.call(u, 'conflict_answer_id')) {
      const coerced = coercePostAnswerIdField(qid, u.conflict_answer_id, idMaps)
      /**
       * Do not remap `conflict_answer_id` back to raw GET row `answer_id`.
       * Conflict resolution must preserve the exact selected branch id from payload.
       */
      next.conflict_answer_id = coerced
    }
    return next
  })
}

/**
 * After {@link finalizePostUpdatesAnswerIds}: block submit when `answer_id` / `conflict_answer_id`
 * are not in the known allowed set for that question (same rule the backend uses for 422).
 * Skips questions with an empty allowed set (no catalog rows to compare against).
 *
 * @param {unknown[]} updates
 * @param {unknown[]|null|undefined} questionsCatalog
 * @param {unknown[]|null|undefined} rawAnswerRows
 * @returns {{ ok: true, message: '' } | { ok: false, message: string, errors: Array<{ qid: string, field: string, value: string }> }}
 */
/** True if `uuid` appears as an option id on GET /questions or merged GET /answers row (multi-select). */
function optionUuidListedForQuestion(row, qid, uuid, questionsCatalog) {
  const qCat = (questionsCatalog || []).find(q => String(q?.question_id) === String(qid))
  const catAns = qCat?.answers
  if (Array.isArray(catAns)) {
    for (const a of catAns) {
      if (a == null || typeof a !== 'object') continue
      const id = a.answer_id ?? a.id
      if (id != null && sameAnswerId(String(id), uuid)) return true
    }
  }
  if (!row) return false
  for (const k of ROW_OPTION_KEYS) {
    const opts = row[k]
    if (!Array.isArray(opts)) continue
    for (const a of opts) {
      if (a == null || typeof a !== 'object') continue
      const id = a.answer_id ?? a.id
      if (id != null && sameAnswerId(String(id), uuid)) return true
    }
  }
  return false
}

export function validatePostUpdatesAnswerIdsBelongToOpportunity(
  updates,
  questionsCatalog,
  rawAnswerRows,
) {
  const idMaps = buildPostAnswerIdMaps(questionsCatalog || [], rawAnswerRows || [])
  const bad = []

  const allowedHas = (m, raw) => {
    const s = String(raw).trim()
    if (!s) return true
    for (const a of m.allowed) {
      if (a === s || sameAnswerId(a, s)) return true
    }
    return false
  }

  const checkField = (qid, val, field) => {
    const m = idMaps.get(String(qid))
    if (!m) return
    if (val == null || val === '') return
    const ids = Array.isArray(val) ? val : [val]
    const row = (rawAnswerRows || []).find(r => String(r?.question_id) === String(qid))
    for (const raw of ids) {
      if (raw == null || String(raw).trim() === '') continue
      const v = String(raw).trim()
      if (m.allowed.size === 0) {
        if (!looksLikeUuid(v)) bad.push({ qid: String(qid), field, value: v })
        continue
      }
      if (allowedHas(m, v)) continue
      if (looksLikeUuid(v) && optionUuidListedForQuestion(row, qid, v, questionsCatalog)) continue
      bad.push({ qid: String(qid), field, value: v })
    }
  }

  for (const u of updates || []) {
    const qid = u?.q_id
    if (qid == null) continue
    if (Object.prototype.hasOwnProperty.call(u, 'answer_id')) {
      checkField(qid, u.answer_id, 'answer_id')
    }
    if (Object.prototype.hasOwnProperty.call(u, 'conflict_answer_id')) {
      checkField(qid, u.conflict_answer_id, 'conflict_answer_id')
    }
  }

  if (bad.length === 0) return { ok: true, message: '' }

  const lines = bad.map(b => `question ${b.qid} · ${b.field} "${b.value}"`)
  const detail = bad.length <= 4 ? lines.join('; ') : `${lines.slice(0, 4).join('; ')}; …+${bad.length - 4} more`
  return {
    ok: false,
    message: `Selected answer_id does not belong to this question for this opportunity. ${detail}. Re-open the card and pick an option again, or refresh answers.`,
    errors: bad,
  }
}

function normalizeMultiSelectAnswerIdsForQuestion(qid, ids, idMaps) {
  const m = idMaps.get(postMapQidKey(qid))
  if (!m || m.allowed.size === 0) {
    return (ids || []).map(x => String(x).trim()).filter(Boolean)
  }
  /**
   * Composite multi-select: some APIs map every studio option id to one backend UUID (single allowed UUID).
   * In that case, coercing destroys which options the user selected. Preserve the original ids so we
   * can build `override_value` from them (labels) later.
   */
  const allowedUuids = [...m.allowed].filter(a => looksLikeUuid(a))
  const compositeSingle = allowedUuids.length === 1
  const allNumeric = (ids || []).length > 0 && (ids || []).every(x => /^\d+$/.test(String(x).trim()))
  if (compositeSingle && allNumeric) {
    return (ids || []).map(x => String(x).trim()).filter(Boolean)
  }
  /**
   * Studio piclist row ids ("54"…"58") — keep them when every token matches a piclist `answer_id`.
   * Otherwise `coerceSinglePostAnswerId` hits a tiny `allowed` set (GET row + one option UUID) and
   * cannot map indices → 422 / unmapped warnings (e.g. QID-023 Jurisdiction/Audit).
   */
  const plistRows = getPiclistAnswerRowsForQuestion(qid)
  if (
    allNumeric &&
    plistRows.length > 0 &&
    (ids || []).every(id => plistRows.some(pr => String(pr.answer_id) === String(id).trim()))
  ) {
    return (ids || []).map(x => String(x).trim()).filter(Boolean)
  }
  const seen = new Set()
  const out = []
  for (const raw of ids || []) {
    if (raw == null || String(raw).trim() === '') continue
    const c = coerceSinglePostAnswerId(qid, raw, idMaps)
    const cs = String(c).trim()
    if (!cs) continue
    let canon = null
    for (const a of m.allowed) {
      if (a === cs || sameAnswerId(a, cs)) {
        canon = a
        break
      }
    }
    if (!canon) {
      /** Row `answer_id` is often one composite id; each option still has its own UUID from GET /questions. */
      if (looksLikeUuid(cs) && !seen.has(cs)) {
        seen.add(cs)
        out.push(cs)
      }
      continue
    }
    if (!seen.has(canon)) {
      seen.add(canon)
      out.push(canon)
    }
  }
  return out
}

function normalizePickAnswerIdForQuestion(qid, sel, idMaps) {
  const m = idMaps.get(postMapQidKey(qid))
  if (!m || m.allowed.size === 0) return sel
  const c = coerceSinglePostAnswerId(qid, sel, idMaps)
  const cs = String(c).trim()
  if (!cs) return sel
  for (const a of m.allowed) {
    if (a === cs || sameAnswerId(a, cs)) return a
  }
  return sel
}

/**
 * Coerce pick / multi-select selection values to canonical answer ids for each question using the same
 * id universe as POST (GET /questions + GET /answers). Strips tokens that do not belong to that question.
 *
 * @param {unknown[]} questions - review question models
 * @param {Record<string, string|string[]>} selections
 * @param {unknown[]|null|undefined} questionsCatalog
 * @param {unknown[]|null|undefined} rawAnswerRows
 */
/** UUIDs present on GET /answers for this row (primary, multi-select, conflicts). */
function collectAnswerRowUuidSet(row) {
  const set = new Set()
  const add = x => {
    const s = String(x ?? '').trim()
    if (!s || !looksLikeUuid(s)) return
    set.add(s.toLowerCase())
  }
  if (!row) return set
  add(row.answer_id)
  if (Array.isArray(row.selected_answer_ids)) {
    for (const x of row.selected_answer_ids) add(x)
  }
  for (const c of row.conflicts || []) add(c?.answer_id)
  return set
}

export function applyPostIdAlignmentToSelections(questions, selections, questionsCatalog, rawAnswerRows) {
  /** String keys so `question_id` 123 and "123" match POST id maps and subset lookups. */
  const out = {}
  for (const [key, val] of Object.entries(selections || {})) {
    if (val !== undefined) out[String(key)] = val
  }
  const idMaps = buildPostAnswerIdMaps(questionsCatalog || [], rawAnswerRows || [])
  const rawByQ = new Map(
    (rawAnswerRows || []).map(r => [postMapQidKey(r?.question_id), r]).filter(([key]) => key),
  )
  for (const q of questions || []) {
    const qKey = q.question_id
    if (qKey == null) continue
    const k = String(qKey)
    if (!Object.prototype.hasOwnProperty.call(out, k)) continue
    const conflictId =
      q?.conflict?.conflict_id != null && String(q.conflict.conflict_id).trim() !== ''
        ? String(q.conflict.conflict_id).trim()
        : null
    const opts = reviewAnswerOptions(q)
    const n = opts.length
    const pick = isReviewPicklistRadiosMode(q, n, conflictId)
    const multi = isReviewMultiSelectMode(q, n, conflictId)
    const m = idMaps.get(postMapQidKey(k))
    if (!m || m.allowed.size === 0) continue
    if (multi && Array.isArray(out[k])) {
      const before = out[k].map(x => String(x).trim()).filter(Boolean)
      out[k] = normalizeMultiSelectAnswerIdsForQuestion(qKey, out[k], idMaps)
      /**
       * When `allowed` is incomplete vs GET /answers, normalization can drop every token → [] and POST
       * builds zero updates. Restore any UUIDs that still belong to this row from the API payload.
       */
      if (Array.isArray(out[k]) && out[k].length === 0 && before.length > 0) {
        const row = rawByQ.get(postMapQidKey(k))
        const rowUuids = collectAnswerRowUuidSet(row)
        const restored = before.filter(x => {
          const s = String(x).trim()
          if (!looksLikeUuid(s)) return false
          return rowUuids.has(s.toLowerCase())
        })
        if (restored.length) out[k] = restored
      }
    } else if (pick && typeof out[k] === 'string' && out[k].trim() !== '') {
      const before = out[k].trim()
      out[k] = normalizePickAnswerIdForQuestion(qKey, before, idMaps)
      const after = typeof out[k] === 'string' ? out[k].trim() : ''
      if (!after && looksLikeUuid(before)) {
        const row = rawByQ.get(postMapQidKey(k))
        const rowUuids = collectAnswerRowUuidSet(row)
        if (rowUuids.has(before.toLowerCase())) out[k] = before
      }
    }
  }
  return out
}

/**
 * Restrict `selections` to keys that match a `questions[].question_id`, then run
 * {@link applyPostIdAlignmentToSelections}. Drops stale keys so answer ids are not paired with the wrong question on POST.
 *
 * @param {unknown[]} questions
 * @param {Record<string, string|string[]>|null|undefined} selections
 * @param {unknown[]|null|undefined} questionsCatalog
 * @param {unknown[]|null|undefined} rawAnswerRows
 * @returns {Record<string, string|string[]>}
 */
export function buildAlignedSelectionsRecordForPost(questions, selections, questionsCatalog, rawAnswerRows) {
  const raw = selections || {}
  const subset = {}
  for (const q of questions || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = String(qid)
    let val
    if (Object.prototype.hasOwnProperty.call(raw, k)) val = raw[k]
    else if (typeof qid !== 'string' && Object.prototype.hasOwnProperty.call(raw, qid)) val = raw[qid]
    if (val !== undefined) subset[k] = val
  }
  return applyPostIdAlignmentToSelections(questions, subset, questionsCatalog || [], rawAnswerRows || [])
}

/**
 * Ordered `{ question_id, answer_id? }[]` in review-question order — explicit question↔selection pairs for POST mapping checks.
 * `answer_id` is a string (pick), string[] (multi), or omitted when there is no selection.
 *
 * @param {unknown[]} questions
 * @param {Record<string, string|string[]>} alignedRecord - e.g. output of {@link buildAlignedSelectionsRecordForPost}
 * @returns {Array<{ question_id: string, answer_id?: string|string[] }>}
 */
export function selectionsRecordToPostAnswerPairList(questions, alignedRecord) {
  const rec = alignedRecord || {}
  const out = []
  for (const q of questions || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = String(qid)
    const row = { question_id: k }
    if (Object.prototype.hasOwnProperty.call(rec, k)) row.answer_id = rec[k]
    out.push(row)
  }
  return out
}

/**
 * Build POST /opportunities/{id}/answers `updates[]` (see `postOpportunityUpdates` in opportunityReviewApi.js).
 * @param {Record<string, string|string[]>} apiSelections
 * @param {{ qState?: Record<string, { status?: string, editedAnswer?: string }>, rawAnswerRows?: unknown[], opportunityId?: string, questionsCatalog?: unknown[] }} [options]
 */
export function buildOpportunityReviewUpdates(questions, apiSelections, options = {}) {
  const { qState = {}, rawAnswerRows = [] } = options
  const catalog = options.questionsCatalog || []
  const alignedByQuestion = buildAlignedSelectionsRecordForPost(questions, apiSelections, catalog, rawAnswerRows)
  const opportunityId =
    options.opportunityId != null && String(options.opportunityId).trim() !== ''
      ? String(options.opportunityId).trim()
      : String(rawAnswerRows[0]?.opportunity_id ?? rawAnswerRows[0]?.opportunityId ?? '').trim() || null
  const rawByQ = new Map(
    (rawAnswerRows || []).map(r => [postMapQidKey(r.question_id), r]).filter(([k]) => k),
  )

  // If no real API data, don't submit updates to avoid ID mismatches
  if (!rawAnswerRows || rawAnswerRows.length === 0) {
    console.warn('⚠️ No API answer data available - skipping submission to avoid ID mismatches')
    return []
  }

  const idMaps = buildPostAnswerIdMaps(catalog, rawAnswerRows)
  const updates = []

  /**
   * When the user simply clicks Accept without interacting with the control, `apiSelections` can be empty
   * for that qid. In that case, fall back to the GET /answers row so we still emit a non-override update.
   *
   * @returns {string|string[]|null}
   */
  function deriveAcceptedSelectionFromRawRow(q, rawRow) {
    const at = String(rawRow?.answer_type ?? rawRow?.answerType ?? q?.answer_type ?? q?.answerType ?? '')
      .toLowerCase()
      .replace(/[\s-]+/g, '_')
    if (at.includes('multi')) {
      if (Array.isArray(rawRow?.selected_answer_ids) && rawRow.selected_answer_ids.length) {
        return rawRow.selected_answer_ids.map(x => String(x).trim()).filter(Boolean)
      }
      const av = rawRow?.answer_value ?? rawRow?.value
      if (typeof av === 'string' && av.trim().startsWith('[')) {
        return parseSerializedListAnswerValue(av)
          .map(x => String(x).trim())
          .filter(Boolean)
      }
      if (Array.isArray(av)) return av.map(x => String(x).trim()).filter(Boolean)
      if (rawRow?.answer_id != null && String(rawRow.answer_id).trim() !== '') return [String(rawRow.answer_id).trim()]
      return null
    }
    // picklist / single
    if (rawRow?.answer_id != null && String(rawRow.answer_id).trim() !== '') return String(rawRow.answer_id).trim()
    const av = rawRow?.answer_value ?? rawRow?.value
    if (av != null && String(av).trim() !== '' && !String(av).trim().startsWith('[')) return String(av).trim()
    return null
  }

  for (const q of questions || []) {
    const qid = q.question_id
    const rawRowForQ = rawByQ.get(String(qid ?? '')) || {}
    /** Always emit a row for GET `active` answers too — backend reconciliation expects updates for every reviewed question. */

    const conflictId = resolveConflictIdForPost(rawRowForQ, q, opportunityId)
    let sel = selectionRecordGet(alignedByQuestion, qid)
    const opts = reviewAnswerOptions(q)
    const n = opts.length
    const pick = isReviewPicklistRadiosMode(q, n, Boolean(conflictId))
    const multi = isReviewMultiSelectMode(q, n, Boolean(conflictId))
    const st = qState[qid]
    const manualEditedAnswer = String(st?.editedAnswer ?? '').trim()
    const manualOverrideAnswer = String(st?.override ?? '').trim()
    const selectedAnswerValue = selectionToSubmitAnswerValue(q, sel)
    const backendAnswerValue = normalizeRawAnswerForSubmit(rawRowForQ?.answer_value)
    const compareAnswerType = normalizeAnswerType(q)
    const finalAnswerForPayload =
      manualEditedAnswer ||
      manualOverrideAnswer ||
      selectedAnswerValue ||
      backendAnswerValue ||
      null
    const manualCurrentValue = manualOverrideAnswer || manualEditedAnswer
    const persistedUserOverride = normalizeBooleanLike(rawRowForQ?.is_user_override) === true
    const forceUserOverrideFromState =
      String(st?.status ?? '').trim().toLowerCase() === 'overridden' &&
      manualCurrentValue !== ''
    const preserveUserOverrideIntent = persistedUserOverride || forceUserOverrideFromState
    const hasDirtyManualInput =
      manualCurrentValue !== '' &&
      isAnswerOverride(manualCurrentValue, backendAnswerValue, {
        answerType: compareAnswerType,
        options: opts,
      })

    const selEmpty =
      sel == null ||
      (typeof sel === 'string' && sel.trim() === '') ||
      (Array.isArray(sel) && sel.length === 0)
    /**
     * Fill from GET when the UI never wrote a selection (Accept without touching the control).
     * Skip `pending` — user has not accepted that card yet.
     */
    if (selEmpty && st?.status !== 'overridden' && st?.status !== 'pending') {
      const derived = deriveAcceptedSelectionFromRawRow(q, rawRowForQ)
      if (derived != null) sel = derived
    }

    const push = row => {
      const feedback = qState[qid]?.feedback
      const feedbackText = qState[qid]?.feedbackText || ''
      /** Preserve star score in comments; `feedback_type` is only the category integer for the DB. */
      let commentsForPost = String(feedbackText || '').trim()
      const starN = Number(feedback)
      if (Number.isFinite(starN) && starN >= 1 && starN <= 5) {
        const starNote = `[rating ${starN}/5]`
        commentsForPost = commentsForPost ? `${commentsForPost} ${starNote}` : starNote
      }
      let out = { ...row }

      /**
       * Assist sometimes stores the chosen option id in editedAnswer/override_value. That should be sent
       * as answer_id, not as free-text override. IDs may not appear in `reviewAnswerOptions` when the
       * catalog/piclist differs from GET /questions UUIDs — still treat as backend answer_id.
       */
      if (
        out.is_user_override &&
        out.override_value != null &&
        !Array.isArray(out.override_value) &&
        looksLikeUuid(String(out.override_value))
      ) {
        const uuid = String(out.override_value).trim()
        const aid = resolveCanonicalAnswerId(q, uuid) ?? (looksLikeUuid(uuid) ? uuid : null)
        if (conflictId) {
          /** Product: any resolved conflict branch sends the same canonical id on both fields. */
          out = {
            ...out,
            answer_id: aid,
            conflict_id: conflictId,
            conflict_answer_id: aid,
            is_user_override: true,
            override_value: undefined,
          }
        } else {
          out = {
            ...out,
            answer_id: aid,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: true,
            override_value: undefined,
          }
        }
      }

      /** Only send feedback fields when the user set a star rating on the Feedback tab (`feedback` is 1–5). */
      const hasFeedback = feedback != null && feedback !== ''
      const payload = { ...out }
      payload.answer_value = finalAnswerForPayload
      const selectedLabel = selectionToSubmitAnswerValue(q, sel) || null
      const selectedRawId =
        typeof sel === 'string'
          ? sel.trim() || null
          : Array.isArray(sel)
            ? sel.map(v => String(v ?? '').trim()).filter(Boolean)
            : null
      const backendOptions = opts.map(o => ({
        answer_id: String(o.id ?? '').trim(),
        answer_value: String(o.text ?? '').trim(),
      }))
      const finalAnswerId =
        payload.answer_id ??
        payload.conflict_answer_id ??
        null
      console.log('[POST mapping]', {
        qid,
        selectedLabel,
        selectedRawId,
        backendOptions,
        finalAnswerId,
      })
      if ((selectedLabel || selectedRawId) && finalAnswerId == null && (pick || multi)) {
        console.warn('[POST mapping] Selected value exists but no backend UUID found', {
          qid,
          selectedLabel,
          selectedRawId,
          backendOptions,
        })
      }
      if (forceUserOverrideFromState && payload.is_user_override !== true) {
        payload.is_user_override = true
        if (payload.override_value == null || String(payload.override_value).trim() === '') {
          const fallbackOverrideValue =
            manualOverrideAnswer ||
            manualEditedAnswer ||
            selectedAnswerValue ||
            finalAnswerForPayload
          if (fallbackOverrideValue != null && String(fallbackOverrideValue).trim() !== '') {
            payload.override_value = fallbackOverrideValue
          }
        }
      }
      /**
       * Only preserve the user-override intent when there is actually an override_value to send.
       * Setting is_user_override=true without override_value causes a backend validation error.
       */
      if (preserveUserOverrideIntent && payload.is_user_override !== true) {
        const hasOverrideVal =
          payload.override_value != null &&
          !(typeof payload.override_value === 'string' && String(payload.override_value).trim() === '') &&
          !(Array.isArray(payload.override_value) && payload.override_value.length === 0)
        if (hasOverrideVal) {
          payload.is_user_override = true
        }
      }
      payload.answer_value = sanitizeAnswerValueForWire(
        q,
        rawRowForQ,
        payload.conflict_answer_id ?? payload.answer_id ?? null,
        payload.answer_value,
      )
      if (hasFeedback) {
        payload.feedback_type = normalizeFeedbackTypeForWire(feedback)
        payload.feedback_id = generateFeedbackId()
        payload.comments = String(feedbackText || '')
      }

      updates.push(payload)
    }

    /**
     * Hard guarantee: if a card is accepted (or otherwise not pending/overridden) but no selection exists,
     * POST the persisted GET /answers `answer_id` (and for multi, the stored selection list) as a plain
     * non-override update. This prevents “random UUID” swaps from catalog label alignment and ensures
     * accepted questions are not dropped from the payload.
     */
    const nowSelEmpty =
      sel == null ||
      (typeof sel === 'string' && sel.trim() === '') ||
      (Array.isArray(sel) && sel.length === 0)
    const rawStatus = String(rawRowForQ?.status ?? '').trim().toLowerCase()
    /**
     * Some screens do not populate `qState[qid]` for every row (it may be undefined),
     * but GET /answers still marks rows as `active`. We treat `active` as reviewed enough
     * to POST the persisted baseline when the selection is empty, to avoid dropping QIDs.
     */
    const isReviewedNonOverrideState =
      (st?.status != null && st.status !== 'pending' && st.status !== 'overridden') ||
      (st?.status == null && rawStatus === 'active')

    /**
     * Rows that carry `conflicts[]` but no backend group `conflict_id`:
     * - AI-selected conflict option → `conflict_id` = selected option's `answer_id`
     * - User text override         → `conflict_id: null, is_user_override: true`
     *
     * These rows must be handled here before the plain pick/multi/text branches, which
     * would otherwise send `conflict_id: null` without `is_user_override`, causing the
     * backend to reject with "conflict_id not found".
     */
    if (!conflictId && Array.isArray(rawRowForQ?.conflicts) && rawRowForQ.conflicts.length > 0) {
      const conflictsArr = rawRowForQ.conflicts
      const isUserOverrideForConflict =
        st?.status === 'overridden' ||
        (String(st?.answerSource ?? '').trim().toLowerCase() === 'user' &&
          String(st?.editedAnswer ?? '').trim() !== '')

      if (isUserOverrideForConflict) {
        // User manually entered an answer — conflict_id is not required
        const userText = String(st?.editedAnswer ?? st?.override ?? '').trim()
        if (userText) {
          push({
            q_id: qid,
            answer_id:
              rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
                ? String(rawRowForQ.answer_id).trim()
                : null,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: true,
            override_value: userText,
          })
        }
        continue
      }

      // AI-selected conflict option: use the selected option's answer_id as conflict_id
      const pinnedCaid =
        st?.conflictAnswerId != null && String(st.conflictAnswerId).trim() !== ''
          ? String(st.conflictAnswerId).trim()
          : null
      const selStrForConflict = pickSelectionString(sel)

      let selectedConflictAnswerId = null
      if (pinnedCaid) {
        // Prefer the conflict answer id pinned by the UI when the user resolved the modal
        selectedConflictAnswerId = pinnedCaid
      } else if (selStrForConflict) {
        // Match the selection string against conflict options by id or display value
        const hit = conflictsArr.find(
          c =>
            String(c.answer_id ?? '').trim() === selStrForConflict ||
            String(c.answer_value ?? '').trim() === selStrForConflict,
        )
        selectedConflictAnswerId = hit?.answer_id ? String(hit.answer_id).trim() : null
      }

      if (selectedConflictAnswerId) {
        push({
          q_id: qid,
          conflict_id: selectedConflictAnswerId,
          conflict_answer_id: selectedConflictAnswerId,
          is_user_override: false,
        })
      }
      // If no conflict option was selected and no user override, skip.
      // Upstream validation (validateReviewSelectionsForSubmit) should have already
      // blocked submission for unresolved conflict rows.
      continue
    }

    if (!conflictId && isReviewedNonOverrideState && nowSelEmpty) {
      const at = normalizeAnswerType(q)
      if (at === 'multi_select') {
        const baseIds = deriveAcceptedSelectionFromRawRow(q, rawRowForQ)
        const ids = Array.isArray(baseIds) ? baseIds : baseIds ? [String(baseIds)] : []
        if (ids.length > 0) {
          // Composite multi-select: one backend UUID + values in answer_value; unchanged accept should be non-override.
          if (isCompositeMultiSelectSingleBackendId(q, rawRowForQ, idMaps)) {
            const base =
              rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
                ? String(rawRowForQ.answer_id).trim()
                : [...(idMaps.get(String(qid))?.allowed ?? [])].find(a => looksLikeUuid(a)) ?? null
            if (base) {
              push({
                q_id: qid,
                answer_id: base,
                conflict_id: null,
                conflict_answer_id: null,
                is_user_override: false,
              })
              continue
            }
          }
          // Non-composite: send one update per selected id (same format as regular multi path).
          for (const rid of ids) {
            push({
              q_id: qid,
              answer_id: rid,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: false,
            })
          }
          continue
        }
      } else {
        const baseId =
          rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
            ? String(rawRowForQ.answer_id).trim()
            : null
        if (baseId) {
          push({
            q_id: qid,
            answer_id: baseId,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          })
          continue
        }
      }
      // If we truly have no baseline id, fall through to the existing logic (may skip).
    }

    if (conflictId) {
      const selStr =
        pickSelectionString(sel) ||
        (st?.conflictResolved ? String(st?.editedAnswer ?? '').trim() : '')
      if (!selStr) {
        if (finalAnswerForPayload) {
          push({
            q_id: qid,
            answer_id: null,
            conflict_id: conflictId,
            conflict_answer_id: null,
            is_user_override: true,
            override_value: String(finalAnswerForPayload),
          })
        }
        continue
      }

      let chosenId = null
      let baselineText = ''
      let chosenOpt = opts.find(o => String(o.id) === selStr)
      if (chosenOpt) {
        chosenId = String(chosenOpt.id)
        baselineText = String(chosenOpt.text).trim()
      } else {
        chosenOpt = opts.find(o => String(o.text).trim() === selStr)
        if (chosenOpt) {
          chosenId = String(chosenOpt.id)
          baselineText = String(chosenOpt.text).trim()
        }
      }
      if (!chosenId && looksLikeUuid(selStr)) {
        chosenId = selStr
        chosenOpt = opts.find(o => String(o.id) === chosenId)
        baselineText = chosenOpt ? String(chosenOpt.text).trim() : ''
      }
      if (!chosenId) {
        const row = rawByQ.get(postMapQidKey(qid))
        const ca = Array.isArray(row?.conflicts) ? row.conflicts : []
        const hit = ca.find(c => String(c.answer_value ?? '').trim() === selStr)
        if (hit?.answer_id != null && String(hit.answer_id).trim() !== '') {
          chosenId = String(hit.answer_id).trim()
          baselineText = String(hit.answer_value ?? '').trim()
        } else if (row?.answer_id != null && String(row.answer_id).trim() !== '') {
          chosenId = String(row.answer_id).trim()
          baselineText = String(row.answer_value ?? '').trim()
        }
      }
      // If FE selection id is a local/non-UUID id, prefer backend conflict answer_id by selected text.
      if (chosenId && !looksLikeUuid(chosenId)) {
        const row = rawByQ.get(postMapQidKey(qid))
        const ca = Array.isArray(row?.conflicts) ? row.conflicts : []
        const byText = ca.find(c => {
          const t = String(c.answer_value ?? '').trim()
          return t !== '' && (t === selStr || (baselineText && t === baselineText))
        })
        if (byText?.answer_id != null && String(byText.answer_id).trim() !== '') {
          chosenId = String(byText.answer_id).trim()
        }
      }

      const userText =
        st?.status === 'overridden' && String(st?.editedAnswer ?? '').trim() !== '' && !looksLikeUuid(String(st?.editedAnswer ?? ''))
          ? String(st.editedAnswer).trim()
          : String(st?.editedAnswer ?? '').trim() || baselineText || selStr

      const editedC = String(st?.editedAnswer ?? '').trim()
      const optForChosen =
        chosenOpt ?? (chosenId ? opts.find(o => String(o.id) === String(chosenId)) : null)
      const expectedLabel = String(
        baselineText || (optForChosen ? optForChosen.text : '') || selStr,
      ).trim()
      const editedMatchesChosen =
        editedC !== '' &&
        (editedC === expectedLabel ||
          (optForChosen && editedC === String(optForChosen.text).trim()) ||
          (chosenId && editedC === String(chosenId)))
      const isUserOverride =
        st?.status === 'overridden' ||
        (!editedMatchesChosen &&
          expectedLabel !== '' &&
          userText !== '' &&
          userText !== expectedLabel)

      if (isUserOverride) {
        /**
         * IMPORTANT: conflict + user override rows MUST include `conflict_answer_id`.
         * `postOpportunityUpdates()` sanitization will drop override-only rows if they don't have:
         * - `answer_id`, or
         * - both `conflict_id` + `conflict_answer_id`.
         *
         * When the user resolves a conflict in the modal, `QAPage` pins that choice in `qState.conflictAnswerId`.
         * Use it preferentially so this row is never dropped even if the regular option hydration/mapping fails.
         */
        const pinnedConflictAnswerId =
          st?.conflictAnswerId != null && String(st.conflictAnswerId).trim() !== ''
            ? String(st.conflictAnswerId).trim()
            : null
        const caid =
          (pinnedConflictAnswerId ? resolveCanonicalAnswerId(q, pinnedConflictAnswerId) : null) ||
          (pinnedConflictAnswerId && looksLikeUuid(pinnedConflictAnswerId) ? pinnedConflictAnswerId : null) ||
          (chosenId ? resolveCanonicalAnswerId(q, chosenId) : null) ||
          (chosenId && looksLikeUuid(chosenId) ? chosenId : null) ||
          (rawRowForQ?.answer_id != null && looksLikeUuid(String(rawRowForQ.answer_id).trim())
            ? String(rawRowForQ.answer_id).trim()
            : null)
        // For conflict + user override, backend accepts payloads without `answer_id`
        // when `conflict_id` + `conflict_answer_id` are provided. Match that shape.
        push({
          q_id: qid,
          conflict_id: conflictId,
          conflict_answer_id: caid,
          is_user_override: true,
          override_value: userText,
        })
      } else if (chosenId) {
        const aid = resolveCanonicalAnswerId(q, chosenId)
        push({
          q_id: qid,
          answer_id: aid,
          conflict_id: conflictId,
          conflict_answer_id: aid,
          is_user_override: false,
        })
      } else {
        push({
          q_id: qid,
          answer_id: null,
          conflict_id: conflictId,
          conflict_answer_id: null,
          is_user_override: true,
          override_value: userText || selStr,
        })
      }
      continue
    }

    if (multi) {
      const ids = Array.isArray(sel) ? sel.filter(Boolean).map(String) : []
      if (ids.length === 0) {
        if (finalAnswerForPayload) {
          push({
            q_id: qid,
            answer_id: null,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: hasDirtyManualInput,
            ...(hasDirtyManualInput ? { override_value: String(finalAnswerForPayload) } : {}),
          })
        }
        continue
      }

      /**
       * GET /answers stores the row’s own `answer_id` (often one UUID for the whole question). POST must
       * reuse that exact id — not per-option catalog UUIDs remapped in finalize.
       */
      const resolvedIds = Array.from(
        new Set(
          ids
            .map(x => resolveCanonicalAnswerId(q, x))
            .map(x => String(x).trim())
            .filter(Boolean),
        ),
      )
      if (resolvedIds.length === 0) continue

      /**
       * IMPORTANT: `resolvedIds` can collapse multiple picks into one canonical/backend UUID (composite multi rows),
       * which would incorrectly shrink override_value to a single label.
       *
       * override_value must reflect whatever is ticked in the UI, so derive labels from the raw selected ids.
       */
      const fullOverrideValue = multiOverrideLabelsForWire(q, ids, idMaps)

      // Determine "changed" by comparing label sets (order-insensitive), not ids (ids can collapse).
      const baselineLabels = normalizeMultiLabelTokensForCompare(
        baselineMultiLabels(q, rawRowForQ, idMaps),
      )
      const currentLabels = normalizeMultiLabelTokensForCompare(fullOverrideValue)
      const baselineRowId = String(rawRowForQ?.answer_id ?? '').trim()
      const selectionCollapsedToBaselineRowId =
        baselineRowId !== '' &&
        resolvedIds.length === 1 &&
        sameAnswerId(String(resolvedIds[0]), baselineRowId)
      /**
       * Some API rows expose multi baseline as comma/list text while selection alignment collapses to the
       * row UUID (`answer_id`). In that unchanged-accept case we should not emit a false user override.
       */
      const implicitUnchangedAccept =
        selectionCollapsedToBaselineRowId &&
        !hasDirtyManualInput &&
        String(st?.answerSource ?? '').trim().toLowerCase() !== 'user'
      const changed = implicitUnchangedAccept
        ? false
        : sortedLabelKey(baselineLabels) !== sortedLabelKey(currentLabels)

      /** Single wire row: persisted GET `answer_id` when present (covers composite + normal multi rows). */
      if (hasServerBaselineAnswerId(rawRowForQ)) {
        push({
          q_id: qid,
          answer_id: String(rawRowForQ.answer_id).trim(),
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: changed,
          ...(changed && fullOverrideValue.length
            ? { override_value: serializeAssistMultiValue(fullOverrideValue) }
            : {}),
        })
        continue
      }

      /** No GET row id: composite shape (single backend UUID in catalog) or one row per option. */
      if (isCompositeMultiSelectSingleBackendId(q, rawRowForQ, idMaps)) {
        const base = [...(idMaps.get(String(qid))?.allowed ?? [])].find(a => looksLikeUuid(a)) ?? null
        if (base) {
          const displayLabelsComposite = multiOverrideLabelsForWire(q, ids, idMaps)
          const changedC = multiSelectionChangedFromBaseline(q, rawRowForQ, ids, idMaps)
          push({
            q_id: qid,
            answer_id: String(base).trim(),
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: changedC,
            ...(changedC && displayLabelsComposite.length
              ? { override_value: serializeAssistMultiValue(displayLabelsComposite) }
              : {}),
          })
          continue
        }
      }

      for (const rid of resolvedIds) {
        push({
          q_id: qid,
          answer_id: rid,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: changed,
          ...(changed && fullOverrideValue.length
            ? { override_value: serializeAssistMultiValue(fullOverrideValue) }
            : {}),
        })
      }
      continue
    }

    if (pick) {
      let selStr = pickSelectionString(sel)
      if (!selStr && st?.status !== 'overridden') {
        if (finalAnswerForPayload) {
          push({
            q_id: qid,
            answer_id: null,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: hasDirtyManualInput,
            ...(hasDirtyManualInput ? { override_value: String(finalAnswerForPayload) } : {}),
          })
        }
        continue
      }

      const { id: pickedId, text: baselineFromPick } = resolvePickOption(q, selStr)
      const resolvedId = pickedId ? resolveCanonicalAnswerId(q, pickedId) : null
      const baselineText = baselineFromPick || ''

      /** Composite picklist (single backend UUID): send chosen label as override_value, keep GET answer_id. */
      if (
        st?.status !== 'overridden' &&
        resolvedId != null &&
        isCompositePicklistSingleBackendId(q, rawRowForQ, idMaps)
      ) {
        const base = rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
          ? String(rawRowForQ.answer_id).trim()
          : [...(idMaps.get(String(qid))?.allowed ?? [])].find(a => looksLikeUuid(a)) ?? null
        if (base) {
          const coerced = coerceSinglePostAnswerId(String(qid), base, idMaps)
          const ro = optionById(q, resolvedId)
          if (shouldCompositePicklistSendOverrideLabel(q, rawRowForQ, resolvedId, ro, idMaps)) {
            push({
              q_id: qid,
              answer_id: coerced,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: true,
              override_value: pickHumanLabelForOverride(q, resolvedId, ro, selStr, idMaps),
            })
          } else {
            push({
              q_id: qid,
              answer_id: coerced,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: false,
            })
          }
          continue
        }
      }

      if (st?.status === 'overridden') {
        const ov = String(st.override ?? st.editedAnswer ?? '').trim()
        if (!ov) continue
        /** When override text is actually a pick id (e.g. "10"), treat it like a selection. */
        if (!selStr) selStr = ov
        const roFromOv = optionById(q, ov)
        let ovHuman = pickHumanLabelForOverride(q, ov, roFromOv, ov, idMaps)
        /** Hard fallback: if still numeric, map via piclist rows. */
        if (/^\d+$/.test(ov) && String(ovHuman).trim() === ov) {
          const pr = getPiclistAnswerRowsForQuestion(String(qid)).find(r => String(r.answer_id) === ov)
          if (pr && String(pr.answer_value ?? '').trim()) ovHuman = String(pr.answer_value).trim()
        }
        if (looksLikeUuid(ov)) {
          const aid = resolveCanonicalAnswerId(q, ov) ?? (looksLikeUuid(ov) ? ov : null)
          if (opts.some(o => sameAnswerId(ov, o.id))) {
            push({
              q_id: qid,
              answer_id: aid,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: false,
            })
            continue
          }
          continue
        }
        if (resolvedId != null && editedMatchesResolvedPick(String(qid), ov, resolvedId, opts)) {
          const wireAid =
            pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, resolvedId, idMaps) ??
            (resolveCanonicalAnswerId(q, resolvedId) ?? resolvedId)
          const ro = optionById(q, resolvedId)
          const composite = isCompositePicklistSingleBackendId(q, rawRowForQ, idMaps)
          const needOverride = composite
            ? shouldCompositePicklistSendOverrideLabel(q, rawRowForQ, resolvedId, ro, idMaps)
            : shouldSendPickUserOverrideForBaselineDelta(q, rawRowForQ, resolvedId, ro, idMaps)
          if (needOverride) {
            push({
              q_id: qid,
              answer_id: wireAid,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: true,
              override_value: pickHumanLabelForOverride(q, resolvedId, ro, ovHuman, idMaps),
            })
          } else {
            push({
              q_id: qid,
              answer_id: wireAid,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: false,
            })
          }
          continue
        }
        /**
         * Override text that isn't free text (often studio id like "2"/"6"/"9"):
         * keep the stable backend answer_id (GET row) and send the human label in override_value.
         */
        const baseFromGet =
          rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
            ? String(rawRowForQ.answer_id).trim()
            : null
        const baseAid = baseFromGet
          ? coerceSinglePostAnswerId(String(qid), baseFromGet, idMaps)
          : resolvedId
            ? resolveCanonicalAnswerId(q, resolvedId) ?? resolvedId
            : looksLikeUuid(ov)
              ? ov
              : null
        push({
          q_id: qid,
          answer_id: baseAid,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: true,
          override_value: ovHuman,
        })
        continue
      }

      if (!resolvedId) {
        const mappedFromEdited = resolveCanonicalAnswerId(q, st?.editedAnswer)
        if (mappedFromEdited) {
          push({
            q_id: qid,
            answer_id: mappedFromEdited,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          })
          continue
        }
        const ro = optionById(q, selStr)
        push({
          q_id: qid,
          answer_id: null,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: true,
          override_value: pickHumanLabelForOverride(q, selStr, ro, selStr, idMaps),
        })
        continue
      }

      const edited = String(st?.editedAnswer ?? '').trim()
      const resolvedOpt = opts.find(o => String(o.id) === String(resolvedId))
      const expectedLabel = String(
        baselineText || (resolvedOpt ? resolvedOpt.text : '') || selStr,
      ).trim()
      const editedNorm = edited.toLowerCase()
      const expectedNorm = expectedLabel.toLowerCase()
      const editedIsOptionUuid =
        looksLikeUuid(edited) &&
        (sameAnswerId(edited, String(resolvedId ?? '')) ||
          opts.some(o => sameAnswerId(edited, o.id)))
      const isUserOverride =
        edited !== '' &&
        expectedLabel !== '' &&
        editedNorm !== expectedNorm &&
        !(resolvedOpt && editedNorm === String(resolvedOpt.text).trim().toLowerCase()) &&
        !editedMatchesResolvedPick(String(qid), edited, resolvedId, opts)

      if (editedIsOptionUuid) {
        const sid = resolveCanonicalAnswerId(q, edited) ?? (looksLikeUuid(edited) ? edited : null)
        const ro = optionById(q, sid)
        if (shouldSendPickUserOverrideForBaselineDelta(q, rawRowForQ, sid, ro, idMaps)) {
          push({
            q_id: qid,
            answer_id:
              pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, sid, idMaps) ??
              sid,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: true,
            override_value: pickHumanLabelForOverride(q, sid, ro, edited, idMaps),
          })
        } else {
          push({
            q_id: qid,
            answer_id: sid,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          })
        }
        continue
      }

      if (isUserOverride) {
        const baseAid =
          pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, resolvedId, idMaps) ??
          (resolvedId ? resolveCanonicalAnswerId(q, resolvedId) ?? resolvedId : null)
        const ro = optionById(q, resolvedId)
        push({
          q_id: qid,
          answer_id: baseAid,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: true,
          override_value: pickHumanLabelForOverride(q, edited, ro, edited, idMaps),
        })
        continue
      }

      const submitId = resolveCanonicalAnswerId(q, resolvedId)
      const ro = resolvedOpt ?? optionById(q, resolvedId)
      if (shouldSendPickUserOverrideForBaselineDelta(q, rawRowForQ, resolvedId, ro, idMaps)) {
        push({
          q_id: qid,
          answer_id:
            pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, resolvedId, idMaps) ??
            submitId,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: true,
          override_value: pickHumanLabelForOverride(q, resolvedId, ro, selStr, idMaps),
        })
      } else {
        push({
          q_id: qid,
          answer_id: submitId,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: false,
        })
      }
      continue
    }

    const preview = reviewStaticAnswerPreview(q)
    const selStr = pickSelectionString(sel)
    const fallbackId = q.final_answer_id != null ? String(q.final_answer_id).trim() : null
    const firstOptId = opts[0]?.id != null ? String(opts[0].id) : null

    const edited = String(st?.editedAnswer ?? '').trim()
    const userTextPlain = edited || selStr.trim()
    const previewNorm = String(preview ?? '').trim()
    const rawAv =
      rawRowForQ?.answer_value != null && String(rawRowForQ.answer_value).trim() !== ''
        ? String(rawRowForQ.answer_value).trim()
        : rawRowForQ?.value != null
          ? String(rawRowForQ.value).trim()
          : ''
    const rowHasSubstantiveAnswer =
      rawAv !== '' &&
      !rawAv.startsWith('[') &&
      rawAv !== 'No extracted answer available for this question.' &&
      rawAv !== 'No extracted answer available in payload for this question.'
    const previewIsEmptyOrPlaceholder =
      previewNorm === '' ||
      previewNorm === 'No extracted answer available for this question.' ||
      previewNorm === 'No extracted answer available in payload for this question.'
    /** No copy from GET row and nothing useful in merged preview → user is filling a blank. */
    const noMeaningfulAiPreview = !rowHasSubstantiveAnswer && previewIsEmptyOrPlaceholder
    const userTextIsPlaceholder =
      userTextPlain === 'No extracted answer available for this question.' ||
      userTextPlain === 'No extracted answer available in payload for this question.'
    /** Prefer GET /answers `answer_id`; else catalog `final_answer_id` (same opportunity). */
    const wireIdFromGet =
      rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
        ? String(rawRowForQ.answer_id).trim()
        : fallbackId

    /**
     * Plain text / integer (non-pick, non-multi): no AI copy in the model, user typed in the blank —
     * POST GET's `answer_id` + `override_value` = user text (matches QID-006 / QID-028 style rows).
     */
    if (
      userTextPlain !== '' &&
      !userTextIsPlaceholder &&
      wireIdFromGet &&
      noMeaningfulAiPreview
    ) {
      const coerced = coerceSinglePostAnswerId(String(qid), wireIdFromGet, idMaps)
      push({
        q_id: qid,
        answer_id: coerced,
        conflict_id: null,
        conflict_answer_id: null,
        is_user_override: true,
        override_value: userTextPlain,
      })
      continue
    }

    const over = String(st?.editedAnswer ?? '').trim()
    const hasExplicitOverride = st?.status === 'overridden' && over !== '' && !looksLikeUuid(over)
    const editedDiffers =
      edited !== '' &&
      isAnswerOverride(edited, preview, {
        answerType: compareAnswerType,
        options: opts,
      })

    if (hasExplicitOverride) {
      const baseAid =
        pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, selStr || fallbackId, idMaps) ??
        resolveCanonicalAnswerId(q, selStr) ??
        resolveCanonicalAnswerId(q, fallbackId) ??
        resolveCanonicalAnswerId(q, firstOptId) ??
        null
      push({
        q_id: qid,
        answer_id: baseAid,
        conflict_id: null,
        conflict_answer_id: null,
        is_user_override: true,
        override_value: over,
      })
      continue
    }

    if (editedDiffers) {
      const baseAid =
        pickWireAnswerIdForPicklistPost(String(qid), rawRowForQ, selStr || fallbackId, idMaps) ??
        resolveCanonicalAnswerId(q, selStr) ??
        resolveCanonicalAnswerId(q, fallbackId) ??
        resolveCanonicalAnswerId(q, firstOptId) ??
        null
      push({
        q_id: qid,
        answer_id: baseAid,
        conflict_id: null,
        conflict_answer_id: null,
        is_user_override: true,
        override_value: edited,
      })
      continue
    }

    let answerId = null
    const cands = [selStr, fallbackId, firstOptId].filter(Boolean)
    for (const cand of cands) {
      answerId = resolveCanonicalAnswerId(q, cand)
      if (answerId) break
    }
    for (const cand of cands) {
      if (!answerId && looksLikeUuid(String(cand))) answerId = String(cand).trim()
    }

    if (!answerId) {
      if (finalAnswerForPayload) {
        push({
          q_id: qid,
          answer_id: null,
          conflict_id: null,
          conflict_answer_id: null,
          is_user_override: hasDirtyManualInput,
          ...(hasDirtyManualInput ? { override_value: String(finalAnswerForPayload) } : {}),
        })
      }
      continue
    }

    push({
      q_id: qid,
      answer_id: answerId,
      conflict_id: null,
      conflict_answer_id: null,
      is_user_override: false,
    })
  }

  /**
   * Second pass: main loop can still skip QIDs (empty selection + branch ordering). After “Accept all”,
   * emit a minimal non-override row from GET /answers for every **non-pending** question that has
   * baseline data and is not already represented in `updates[]`.
   */
  const coveredQids = new Set(updates.map(u => String(u.q_id ?? '')))
  for (const q of questions || []) {
    const qid = q?.question_id
    if (qid == null) continue
    const k = String(qid)
    if (coveredQids.has(k)) continue
    const st = qState[qid]
    if (st?.status === 'pending') continue
    const rawRowForQ = rawByQ.get(k) || {}
    const conflictId = resolveConflictIdForPost(rawRowForQ, q, opportunityId)
    const hasManualAnswer =
      String(st?.answerSource ?? '').trim().toLowerCase() === 'user' &&
      String(st?.editedAnswer ?? '').trim() !== ''
    if (conflictId && !st?.conflictResolved && !hasManualAnswer) continue
    const opts = reviewAnswerOptions(q)
    const n = opts.length
    const multi = isReviewMultiSelectMode(q, n, Boolean(conflictId))
    const derived = deriveAcceptedSelectionFromRawRow(q, rawRowForQ)
    const hasBaseline = hasServerBaselineAnswerId(rawRowForQ) || derived != null
    // For non-extracted questions with a user-entered answer, allow even without a baseline
    if (!hasBaseline && !hasManualAnswer) continue

    const applyFeedback = base => {
      const feedback = qState[qid]?.feedback
      const feedbackText = qState[qid]?.feedbackText || ''
      const hasFeedback = feedback != null && feedback !== ''
      if (!hasFeedback) return base
      return {
        ...base,
        feedback_type: normalizeFeedbackTypeForWire(feedback),
        feedback_id: generateFeedbackId(),
        comments: String(feedbackText || ''),
      }
    }

    if (multi) {
      const ids = Array.isArray(derived) ? derived.filter(Boolean).map(String) : derived ? [String(derived)] : []
      if (ids.length === 0) continue
      if (hasServerBaselineAnswerId(rawRowForQ)) {
        updates.push(
          applyFeedback({
            q_id: qid,
            answer_id: String(rawRowForQ.answer_id).trim(),
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          }),
        )
      } else if (isCompositeMultiSelectSingleBackendId(q, rawRowForQ, idMaps)) {
        const base = [...(idMaps.get(String(qid))?.allowed ?? [])].find(a => looksLikeUuid(a)) ?? null
        if (!base) continue
        updates.push(
          applyFeedback({
            q_id: qid,
            answer_id: String(base).trim(),
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          }),
        )
      } else {
        for (const rid of ids) {
          updates.push(
            applyFeedback({
              q_id: qid,
              answer_id: rid,
              conflict_id: null,
              conflict_answer_id: null,
              is_user_override: false,
            }),
          )
        }
      }
    } else {
      const baseId =
        rawRowForQ?.answer_id != null && String(rawRowForQ.answer_id).trim() !== ''
          ? String(rawRowForQ.answer_id).trim()
          : typeof derived === 'string'
            ? derived
            : null
      if (!baseId && !hasManualAnswer) continue
      if (hasManualAnswer && !baseId) {
        // Non-extracted question with user-entered answer but no backend baseline —
        // emit as a user override so the manual answer is submitted.
        updates.push(
          applyFeedback({
            q_id: qid,
            answer_id: null,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: true,
            override_value: String(st.editedAnswer).trim(),
          }),
        )
      } else {
        updates.push(
          applyFeedback({
            q_id: qid,
            answer_id: baseId,
            conflict_id: null,
            conflict_answer_id: null,
            is_user_override: false,
          }),
        )
      }
    }
    coveredQids.add(k)
  }

  return finalizePostUpdatesAnswerIds(updates, idMaps, rawByQ)
}
