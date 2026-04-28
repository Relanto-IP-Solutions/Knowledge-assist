import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { allSections } from '../data'
import { groupAnswersByQaCatalog, placementForQuestionId } from '../config/qidPlacement'
import { toApiOpportunityId, useOpportunityAnswersApi } from '../config/opportunityApi'
import { useOpportunityQaBundle } from '../hooks/useOpportunityQaBundle'
import { postOpportunityUpdates, fetchOpportunityQuestions } from '../services/opportunityReviewApi'
import { fetchOpportunityAnswers } from '../services/opportunityAnswersApi'
import { fetchOpportunityIds } from '../services/opportunityIdsApi'
import {
  buildOpportunityExportRows,
  downloadCsv,
  downloadWordHtmlDoc,
  downloadExportPdf,
} from '../utils/opportunityExport'
import { ConflictResolutionModal } from './ConflictResolutionModal'
import { QuestionCard } from './QuestionCard'
import { apiAnswerElementId } from './ApiAnswerCard'
import { apiAnswerNeedsConflictClarify, buildQuestionCardModelFromApiAnswer } from '../utils/mapApiAnswerToQuestionCard'
import {
  applyPostIdAlignmentToSelections,
  buildOpportunityReviewUpdates,
  hasExtractedAnswerConflicts,
  isReviewMultiSelectMode,
  isReviewPicklistRadiosMode,
  mergeApiSelectionsForSubmit,
  normalizeAnswerType,
  requiresAssistSelectionForAccept,
  reviewAnswerOptions,
  selectionRecordGet,
  validatePostConflictIds,
  validatePostUpdatesAnswerIdsBelongToOpportunity,
  validateRequiredReviewQuestions,
  validateReviewSelectionsForSubmit,
} from '../utils/opportunityReviewMeta'
import { isAnswerOverrideAgainstAny } from '../utils/overrideDetection'
import { OpportunityAnswersSkeleton } from './OpportunityAnswersSkeleton'

/** Preserve GET /answers UUIDs; do not remap through studio piclist. */
function looksLikeAnswerUuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(s ?? '').trim(),
  )
}
import {
  opportunityAnswerRowToReviewQuestion,
  parseSerializedListAnswerValue,
  serializeAssistMultiValue,
} from '../utils/opportunityAnswerRowToReviewQuestion'

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'
const QA_PROGRESS_STORAGE_PREFIX = 'knowledgeAssist:qaProgress:v1'

function getQaProgressStorageKey(oppId) {
  const key = String(oppId ?? '').trim()
  if (!key) return ''
  return `${QA_PROGRESS_STORAGE_PREFIX}:${key}`
}

function readQaProgress(oppId) {
  const storageKey = getQaProgressStorageKey(oppId)
  if (!storageKey) return null
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

function persistQaProgress(oppId, payload) {
  const storageKey = getQaProgressStorageKey(oppId)
  if (!storageKey) return
  try {
    localStorage.setItem(storageKey, JSON.stringify(payload))
  } catch {
    /* noop */
  }
}

// ── Per-opportunity accepted-answers persistence ──────────────────────────────
// Key format: accepted_<opportunity_id>
// Value:      { [question_id]: true }  (only accepted/overridden questions)
// This is intentionally separate from the broader qaProgress snapshot so it can
// be read, written, and merged with the API response without touching other state.

function getAcceptedStorageKey(oppId) {
  const key = String(oppId ?? '').trim()
  if (!key) return ''
  return `accepted_${key}`
}

function readAcceptedAnswers(oppId) {
  const storageKey = getAcceptedStorageKey(oppId)
  if (!storageKey) return {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return parsed
  } catch {
    return {}
  }
}

function writeAcceptedAnswers(oppId, acceptedMap) {
  const storageKey = getAcceptedStorageKey(oppId)
  if (!storageKey) return
  try {
    localStorage.setItem(storageKey, JSON.stringify(acceptedMap))
  } catch {
    /* noop */
  }
}

// ── Session-based accepted-answer saves (per section) ─────────────────────────
// Stores only accepted answers in sessionStorage so they survive navigation
// within the tab but clear automatically when the browser session ends.
// Separate from the broader qaProgress snapshot — this holds only the "explicitly
// saved" accepted entries (no pending / temporary state).
const KA_SESSION_SAVE_KEY_PREFIX = 'ka:sectionSave:v1'

function getSessionSaveKey(oppId) {
  const key = String(oppId ?? '').trim()
  if (!key) return ''
  return `${KA_SESSION_SAVE_KEY_PREFIX}:${key}`
}

function readSessionSaves(oppId) {
  const storageKey = getSessionSaveKey(oppId)
  if (!storageKey) return []
  try {
    const raw = sessionStorage.getItem(storageKey)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeSessionSaves(oppId, answers) {
  const storageKey = getSessionSaveKey(oppId)
  if (!storageKey) return
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(answers))
  } catch { /* noop */ }
}

function clearSessionSaves(oppId) {
  const storageKey = getSessionSaveKey(oppId)
  if (!storageKey) return
  try {
    sessionStorage.removeItem(storageKey)
  } catch { /* noop */ }
}

/**
 * Wipe every QA-related storage entry across all opportunities.
 * Call this on user logout so no session or progress data is left behind.
 */
export function clearAllQaStorage() {
  try {
    const keysToRemove = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (
        k &&
        (k.startsWith(QA_PROGRESS_STORAGE_PREFIX) || k.startsWith('accepted_'))
      ) {
        keysToRemove.push(k)
      }
    }
    keysToRemove.forEach(k => localStorage.removeItem(k))
    // sessionStorage holds all KA_SESSION_SAVE_KEY_PREFIX entries
    sessionStorage.clear()
  } catch { /* noop */ }
}

function buildAcceptedMapFromState(qState) {
  const acceptedMap = {}
  for (const [qid, state] of Object.entries(qState || {})) {
    if (state?.status === 'accepted' || state?.status === 'overridden') {
      acceptedMap[String(qid)] = true
    }
  }
  return acceptedMap
}

/** isValidAnswer — checks answer_value only, never answer_type. */
function isValidAnswer(value) {
  if (value == null) return false

  const normalize = s =>
    String(s ?? '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .replace(/[!?.,;:]+$/g, '')

  const isInvalidPlaceholderString = raw => {
    const norm = normalize(raw)
    if (!norm) return true
    if (norm === 'no answer given') return true
    if (norm === 'no answer generated') return true
    if (norm.includes('no extracted answer')) return true
    if (norm.includes('new answer generated')) return true
    // Backend sometimes returns sentinel text instead of null for “no extraction”.
    if (norm === 'nothing') return true
    if (norm === 'null') return true
    if (norm === 'use edited') return true
    return false
  }

  const hasAtLeastOneValidItem = items => items.some(x => !isInvalidPlaceholderString(x))

  if (Array.isArray(value)) return hasAtLeastOneValidItem(value)

  const s = String(value).trim()
  if (s.startsWith('[')) {
    const compact = s.replace(/\s+/g, '')
    if (compact === '[]') return false
    try {
      const parsed = parseSerializedListAnswerValue(s)
      if (parsed.length > 0 && hasAtLeastOneValidItem(parsed)) return true
      return false
    } catch {
      // Fall through to plain-string validation
    }
  }

  return !isInvalidPlaceholderString(s)
}

function toDisplayAnswerText(value) {
  if (value == null) return ''
  if (Array.isArray(value)) {
    return value
      .map(v => String(v ?? '').trim())
      .filter(Boolean)
      .join(', ')
  }
  const raw = String(value).trim()
  if (!raw) return ''
  if (raw.startsWith('[')) {
    const parsed = parseSerializedListAnswerValue(raw)
      .map(v => String(v ?? '').trim())
      .filter(Boolean)
    if (parsed.length > 0) return parsed.join(', ')
  }
  return raw
}

function getAiComparableCandidates(question, row, backendValue) {
  const out = []
  const pushIfAny = (value) => {
    const display = String(resolveSelectionToDisplayValue(question, value) ?? '').trim()
    if (display) out.push(display)
  }
  pushIfAny(backendValue)
  // Some rows are seeded with answer_id UUIDs while backend baseline text lives in answer_value.
  // Include ids as AI-equivalent candidates so unchanged accepts are not misclassified as user edits.
  pushIfAny(row?.answer_id)
  const conflicts = Array.isArray(row?.conflicts) ? row.conflicts : []
  for (const conflict of conflicts) {
    pushIfAny(conflict?.answer_value ?? conflict?.answer ?? conflict?.value)
    pushIfAny(conflict?.answer_id)
  }
  return out
}

function isOverrideAgainstBackend(question, row, currentValue, backendValue) {
  const answerType = normalizeAnswerType(question)
  const options = reviewAnswerOptions(question)
  const aiCandidates = getAiComparableCandidates(question, row, backendValue)
  return isAnswerOverrideAgainstAny(currentValue, aiCandidates, { answerType, options })
}

function getConflictFallbackAnswerFromRow(row) {
  const list = Array.isArray(row?.conflicts) ? row.conflicts : []
  for (const c of list) {
    const raw = c?.answer_value ?? c?.answer ?? null
    if (isValidAnswer(raw)) return toDisplayAnswerText(raw)
  }
  return ''
}

function normalizeConflictCompareText(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

function resolveConflictSelectionIdFromRow(row, chosen, chosenText) {
  if (!row || typeof row !== 'object') return null
  const textNorm = normalizeConflictCompareText(chosenText)
  const chosenRole = String(chosen?.role ?? '').trim().toLowerCase()
  const chosenConflictIndex = Number(chosen?.conflictIndex)

  if (chosenRole === 'primary') {
    const primaryId = String(row?.answer_id ?? '').trim()
    if (primaryId) return primaryId
  }

  const conflicts = Array.isArray(row?.conflicts) ? row.conflicts : []
  if (Number.isFinite(chosenConflictIndex) && chosenConflictIndex > 0) {
    const byIndex = conflicts[chosenConflictIndex - 1]
    const byIndexId = String(byIndex?.answer_id ?? '').trim()
    if (byIndexId) return byIndexId
  }

  if (textNorm && conflicts.length > 0) {
    const byText = conflicts.find(c => {
      const raw = c?.answer_value ?? c?.answer ?? c?.value ?? ''
      return normalizeConflictCompareText(raw) === textNorm
    })
    const byTextId = String(byText?.answer_id ?? '').trim()
    if (byTextId) return byTextId
  }

  const primaryAnswerNorm = normalizeConflictCompareText(row?.answer_value ?? row?.answer ?? '')
  if (textNorm && primaryAnswerNorm && textNorm === primaryAnswerNorm) {
    const primaryId = String(row?.answer_id ?? '').trim()
    if (primaryId) return primaryId
  }

  return null
}

function getEffectiveDisplayAnswer({
  question,
  row,
  qStateEntry,
  selectionValue,
}) {
  const manualEdited = String(qStateEntry?.editedAnswer ?? '').trim()
  const manualOverride = String(qStateEntry?.override ?? '').trim()
  const userCleared = qStateEntry?.userCleared === true
  const conflictResolvedValue = qStateEntry?.conflictResolved
    ? (manualEdited || manualOverride || '')
    : ''
  const selectedLabel = resolveSelectionToDisplayValue(question, selectionValue)
  const backendValue = resolveSelectionToDisplayValue(question, row?.answer_value)
  const conflictFallback = getConflictFallbackAnswerFromRow(row)
  const selectedValueText = String(selectedLabel ?? '').trim()
  const backendValueText = String(backendValue ?? '').trim()
  const conflictFallbackText = String(conflictFallback ?? '').trim()
  const rowHasExtractedPayload = row != null && isValidAnswer(row.answer_value)

  // userCleared should only suppress backend fallback, not newly edited/selected values.
  // Do not use MCQ `apiSelections` display alone when the row has no extraction — that was
  // pre-seeded for submit shape, not a user answer (would allow “Accept” with no AI text).
  const effectiveAnswer =
    conflictResolvedValue ||
    manualEdited ||
    manualOverride ||
    (rowHasExtractedPayload ? selectedValueText : '') ||
    (userCleared ? '' : (backendValueText || conflictFallbackText))

  return {
    effectiveAnswer,
    conflictFallback,
    backendValue,
  }
}

function getAnswerLabelFromSelection(question, selectedId) {
  const sid = String(selectedId ?? '').trim()
  if (!sid) return ''
  if (!question) return sid
  const opts = reviewAnswerOptions(question)
  const hit = opts.find(
    o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
  )
  if (!hit) return sid
  return String(hit.text ?? hit.id ?? sid).trim()
}

function normalizePickSelectionPayload(question, pick) {
  const selectedObj = pick != null && typeof pick === 'object' && !Array.isArray(pick) ? pick : null
  const rawId = String(selectedObj?.answer_id ?? pick ?? '').trim()
  const rawValue = String(selectedObj?.answer_value ?? '').trim()
  if (!rawId && !rawValue) return { answer_id: '', answer_value: '' }
  const opts = reviewAnswerOptions(question)
  const hit = opts.find(o => {
    const id = String(o?.id ?? '').trim()
    const text = String(o?.text ?? '').trim()
    return (
      (rawId && (id === rawId || text === rawId)) ||
      (rawValue && (text === rawValue || id === rawValue))
    )
  })
  const answer_id = String(hit?.id ?? rawId).trim()
  let answer_value = String(hit?.text ?? rawValue).trim()
  if (!answer_value && answer_id) answer_value = getAnswerLabelFromSelection(question, answer_id)
  if (answer_value && answer_id && answer_value === answer_id && hit?.text) {
    answer_value = String(hit.text).trim()
  }
  return { answer_id, answer_value }
}

function resolveSelectionToDisplayValue(question, selection) {
  if (selection == null) return ''
  if (Array.isArray(selection)) {
    const labels = selection
      .map(v => getAnswerLabelFromSelection(question, v))
      .map(v => String(v ?? '').trim())
      .filter(Boolean)
    return labels.join(', ')
  }
  const raw = String(selection).trim()
  if (!raw) return ''
  if (raw.startsWith('[')) {
    const parsed = parseSerializedListAnswerValue(raw)
    if (parsed.length > 0) {
      const labels = parsed
        .map(v => getAnswerLabelFromSelection(question, v))
        .map(v => String(v ?? '').trim())
        .filter(Boolean)
      return labels.join(', ')
    }
  }
  return getAnswerLabelFromSelection(question, raw)
}

function questionCompletionKey(q) {
  if (q?.question_id != null) return String(q.question_id)
  if (q?.id != null) return String(q.id)
  return ''
}

function isQuestionServerLocked(question, qStateEntry) {
  return (
    qStateEntry?.serverLocked === true ||
    String(question?.status ?? '').trim().toLowerCase() === 'active'
  )
}

export function isQuestionComplete(question, qStateEntry) {
  const qid = questionCompletionKey(question)
  const status = String(qStateEntry?.status ?? '').trim().toLowerCase()
  // Backend-submitted/locked rows are not editable; treat them as complete for gating Submit.
  if (isQuestionServerLocked(question, qStateEntry)) {
    console.log('[Completion]', { qid, status, complete: true, reason: 'server-locked' })
    return true
  }
  const edited = String(qStateEntry?.editedAnswer ?? '').trim()
  const override = String(qStateEntry?.override ?? '').trim()
  const backendAnswer = String(
    resolveSelectionToDisplayValue(
      question,
      question?.answer_value ?? question?.answer ?? null,
    ) ?? '',
  ).trim()
  const acceptedStatus = status === 'accepted' || status === 'overridden'
  // complete:true is set by acceptQ (via functional state update) — trust it directly
  // so MCQ answers accepted via assistSelection (no manualValue) are counted complete.
  if (acceptedStatus && qStateEntry?.complete === true) {
    console.log('[Completion]', { qid, status, complete: true, reason: 'complete-flag' })
    return true
  }
  const finalAcceptedAnswer = edited || override || backendAnswer || null
  const complete = acceptedStatus && isValidAnswer(finalAcceptedAnswer)
  console.log('[Section Progress]', {
    qid,
    status,
    editedAnswer: edited || null,
    override: override || null,
    backendAnswer: backendAnswer || null,
    complete,
  })
  return complete
}

/** @deprecated alias kept for callers that still reference old name */
const isValidBackendAiAnswerValue = isValidAnswer

/**
 * Real extracted value on GET /answers row only — does not use catalog “first option” heuristics
 * (see {@link reviewStaticAnswerPreview}, which can return a label when nothing is selected).
 */
/** True when the GET /answers row has a real extracted value (not placeholder / “no extracted answer”). */
function rawRowHasNonPlaceholderAnswerValue(row) {
  if (row == null) return false
  return isValidAnswer(row.answer_value)
}

/** Pure “Accept AI” is allowed only when the row has extracted text or at least one citation. */
function answerRowQualifiesForPureAiAccept(row) {
  if (!row) return false
  if (isValidAnswer(row.answer_value)) return true
  return Array.isArray(row.citations) && row.citations.length > 0
}

function IconCompass({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 7.5l3.2 4.5L12 16.5l-3.2-4.5L12 7.5z" />
    </svg>
  )
}
function IconCash({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <circle cx="12" cy="12" r="2" />
      <path d="M6 12h.01M18 12h.01" />
    </svg>
  )
}
function IconSliders({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />
      <line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" />
    </svg>
  )
}
function IconTrendLine({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M23 6l-9.5 9.5-5-5L1 18" />
      <path d="M17 6h6v6" />
    </svg>
  )
}

const SECTION_ROW_ICON = {
  'saas-architecture-technical-fundamentals': IconCompass,
  'pricing-packaging-commercial-terms': IconCash,
  'integration-implementation': IconSliders,
  'sales-methodology-process': IconTrendLine,
}

function OpportunityExportMenu({ apiOppId, opportunityName, disabled, block, menuAlignLeft }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const close = e => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const run = async kind => {
    if (disabled) return
    setBusy(true)
    try {
      const [answers, questions] = await Promise.all([
        fetchOpportunityAnswers(apiOppId, { bypassCache: true }),
        fetchOpportunityQuestions(apiOppId, { bypassCache: true }),
      ])
      const bundle = buildOpportunityExportRows(answers, questions)
      const safeBase = `${apiOppId}-qualification`.replace(/[^\w.-]+/g, '_')
      const title = `${opportunityName} — qualification export`
      if (kind === 'csv') downloadCsv(bundle, safeBase)
      else if (kind === 'doc') downloadWordHtmlDoc(bundle, title, safeBase)
      else downloadExportPdf(bundle, title, safeBase)
      setOpen(false)
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const item = (label, sub, kind) => (
    <button
      key={kind}
      type="button"
      disabled={busy}
      onClick={() => run(kind)}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        padding: '10px 12px',
        border: 'none',
        borderBottom: '1px solid var(--border)',
        background: busy ? 'var(--bg2)' : 'transparent',
        cursor: busy ? 'wait' : 'pointer',
        fontFamily: 'var(--font)',
        transition: 'background .12s',
      }}
      onMouseEnter={e => { if (!busy) e.currentTarget.style.background = 'rgba(27,38,79,.06)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, color: SI_NAVY }}>{label}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2, lineHeight: 1.35 }}>{sub}</div>
    </button>
  )

  return (
    <div ref={wrapRef} style={{ position: 'relative', width: block ? '100%' : 'auto' }}>
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => !disabled && setOpen(o => !o)}
        style={{
          padding: '8px 14px',
          borderRadius: 10,
          fontSize: 12,
          fontWeight: 700,
          fontFamily: 'var(--font)',
          border: `1px solid ${disabled ? 'var(--border)' : 'rgba(232,83,46,.45)'}`,
          background: disabled ? 'var(--bg3)' : 'linear-gradient(135deg, rgba(255,250,248,.95) 0%, rgba(255,255,255,.98) 100%)',
          color: disabled ? 'var(--text3)' : SI_ORANGE,
          cursor: disabled ? 'not-allowed' : 'pointer',
          whiteSpace: 'nowrap',
          boxShadow: disabled ? 'none' : '0 2px 8px rgba(232,83,46,.12)',
          width: block ? '100%' : 'auto',
          boxSizing: 'border-box',
        }}
      >
        {busy ? '…' : 'Export'}
      </button>
      {open && !disabled && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            ...(menuAlignLeft ? { left: 0 } : { right: 0 }),
            zIndex: 80,
            minWidth: 228,
            background: 'var(--bg2)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            boxShadow: '0 12px 32px rgba(15,23,42,.14)',
            overflow: 'hidden',
          }}
        >
          {item('PDF', 'Download questions and answers as a PDF file', 'pdf')}
          {item('CSV', 'Comma-separated — question and answer per row', 'csv')}
          {item('Word / Docs', 'Download .doc for Word or Google Docs', 'doc')}
        </div>
      )}
    </div>
  )
}

function flattenPredefinedQuestions(oppId) {
  const rows = []
  ;(allSections[oppId] || []).forEach(sec => {
    if (sec.isSummary) return
    sec.signals?.forEach(sig => {
      if (sig.type !== 'ai' || !sig.qs) return
      sig.qs.forEach(q => {
        rows.push({
          id: q.id,
          text: q.text,
          sectionId: sec.id,
          sectionTitle: sec.title,
        })
      })
    })
  })
  return rows
}

function initQAState(oppId) {
  const state = {}
  ;(allSections[oppId] || []).forEach(sec =>
    sec.signals.forEach(sig => {
      if (sig.type === 'ai') sig.qs.forEach(q => {
        state[q.id] = {
          status: q.status,
          isAccepted: q.status === 'accepted' || q.status === 'overridden',
          isEdited: q.status === 'overridden',
          override: q.override || '',
          editedAnswer: '',
          acceptedAnswerValue: '',
          answerSource: 'ai',
          feedback: null,
          feedbackText: '',
          notes: '',
          conflictResolved: false,
        }
      })
    })
  )
  return state
}

const DEFAULT_API_Q_STATE = {
  status: 'pending',
  isAccepted: false,
  isEdited: false,
  override: '',
  editedAnswer: '',
  acceptedAnswerValue: '',
  answerSource: 'ai',
  userCleared: false,
  feedback: null,
  feedbackText: '',
  notes: '',
  conflictResolved: false,
  /** When a conflict is resolved, remember which conflict branch id was chosen. */
  conflictAnswerId: null,
  /** Reserved for flows that need to distinguish server-persisted rows (e.g. POST skip rules in meta). */
  serverLocked: false,
}

/** GET /answers row lifecycle (e.g. active vs pending) — not the same as “user accepted in QA”. */
function isBackendAnswerActive(row) {
  return String(row?.status ?? '').trim().toLowerCase() === 'active'
}

function normalizeBooleanLike(value) {
  if (value === true || value === false) return value
  const t = String(value ?? '').trim().toLowerCase()
  if (t === 'true' || t === '1' || t === 'yes') return true
  if (t === 'false' || t === '0' || t === 'no') return false
  return null
}

/**
 * Submitted opportunity filter must reflect the currently shown accepted label.
 * Prefer payload `is_user_override`, but fall back to local accepted value vs backend AI comparison.
 */
function shouldIncludeAnswerBySubmittedPayloadFilter({
  row,
  filterId,
  qStateEntry,
  reviewQuestion,
}) {
  const payloadOverride = normalizeBooleanLike(row?.is_user_override)
  let isHumanAnswer = payloadOverride === true

  if (payloadOverride == null) {
    const fallbackQuestion =
      reviewQuestion ||
      opportunityAnswerRowToReviewQuestion(row || {}, {
        questionText: row?.question_text,
      })
    const acceptedValue = String(
      qStateEntry?.acceptedAnswerValue ||
      qStateEntry?.override ||
      qStateEntry?.editedAnswer ||
      '',
    ).trim()
    const backendValue = String(
      resolveSelectionToDisplayValue(
        fallbackQuestion,
        row?.answer_value ?? row?.answer ?? '',
      ) || '',
    ).trim()
    const localUserSource = String(qStateEntry?.answerSource ?? '').trim().toLowerCase() === 'user'
    const overriddenStatus = String(qStateEntry?.status ?? '').trim().toLowerCase() === 'overridden'
    const acceptedLooksEdited =
      acceptedValue !== '' &&
      isOverrideAgainstBackend(fallbackQuestion, row, acceptedValue, backendValue)

    isHumanAnswer = localUserSource || overriddenStatus || acceptedLooksEdited
  }

  if (filterId === 'ai') return !isHumanAnswer
  if (filterId === 'human') return isHumanAnswer
  return true
}

function feedbackVoteFromAnswerRow(row) {
  const candidates = [
    row?.feedback,
    row?.feedback_type,
    row?.feedbackType,
    row?.rating,
    row?.score,
  ]
  for (const raw of candidates) {
    if (raw == null || raw === '') continue
    const n = Number(raw)
    if (Number.isFinite(n)) {
      const rounded = Math.round(n)
      if (rounded >= 1 && rounded <= 5) return rounded
    }
  }
  return null
}

function feedbackTextFromAnswerRow(row) {
  const candidates = [
    row?.feedback_text,
    row?.feedbackText,
    row?.comments,
    row?.feedback_comment,
    row?.feedbackComment,
  ]
  for (const raw of candidates) {
    const t = String(raw ?? '').trim()
    if (t) return t
  }
  return ''
}

/**
 * Batch-accept pending rows using merged MCQ selections and in-progress sentence edits.
 * Does not POST — returns the next `qState` snapshot and how many rows changed.
 */
export function applyAcceptAllToQState(prevQState, {
  apiAnswers,
  reviewQuestions,
  apiSelections,
  questionsCatalog,
}) {
  const next = { ...prevQState }
  let changed = 0
  const toCleanString = value => String(value ?? '').trim()

  for (const a of apiAnswers) {
    const qidKey = String(a.question_id)
    const cur = prevQState[qidKey] || DEFAULT_API_Q_STATE
    console.log('[Accept All Processing]', {
      qid: qidKey,
      answerType: String(a?.answer_type ?? '').trim() || null,
      backendAnswer: a?.answer_value ?? null,
      localState: cur,
    })
    if (isBackendAnswerActive(a) || cur.serverLocked) {
      console.log('[AcceptAll]', {
        question_id: qidKey,
        answer_value: a?.answer_value ?? null,
        accepted: false,
        reason: 'backend-active-locked',
      })
      continue
    }
    if (cur.status !== 'pending') {
      console.log('[AcceptAll]', {
        question_id: qidKey,
        answer_value: a?.answer_value ?? null,
        accepted: false,
        reason: 'status-not-pending',
      })
      continue
    }
    if (apiAnswerNeedsConflictClarify(a) && !cur.conflictResolved) {
      console.log('[AcceptAll]', {
        question_id: qidKey,
        answer_value: a?.answer_value ?? null,
        accepted: false,
        reason: 'conflict-not-resolved',
      })
      continue
    }

    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)
    const selectionValue = selectionRecordGet(apiSelections, qidKey)
    const { effectiveAnswer, conflictFallback, backendValue } = getEffectiveDisplayAnswer({
      question: rq,
      row: a,
      qStateEntry: prevQState?.[qidKey],
      selectionValue,
    })
    // Also consider draftAnswer set by onDraftAnswerChange (MCQ label synced before Accept All)
    const draftAnswer = String(prevQState?.[qidKey]?.editedAnswer ?? '').trim()
    const finalValue = draftAnswer || (toCleanString(effectiveAnswer) !== '' ? effectiveAnswer : null)

    const accepted = isValidAnswer(finalValue)
    const backendText = toDisplayAnswerText(backendValue)
    const finalText = draftAnswer || toDisplayAnswerText(finalValue)
    const hasManualOverride = toCleanString(cur.override) !== ''
    const hasManualDraft =
      draftAnswer !== '' &&
      isOverrideAgainstBackend(rq, a, draftAnswer, backendText)
    /**
     * IMPORTANT:
     * `apiSelections` is pre-seeded from backend payload for many unopened sections so those rows can submit.
     * That seeded selection is NOT a user edit. During Accept All, only real manual draft/override deltas
     * should flip the source to `user`; otherwise unopened AI answers get mislabeled as edited.
     * `hasSelectionEdit` uses value comparison against backend AI so a seeded value that still matches
     * does not count as a user edit.
     */
    const hasSelectionValue = toCleanString(selectionValue) !== ''
    const hasSelectionEdit =
      hasSelectionValue &&
      isOverrideAgainstBackend(
        rq,
        a,
        resolveSelectionToDisplayValue(rq, selectionValue),
        backendText,
      )
    const finalDiffersFromBackend =
      finalText !== '' &&
      isOverrideAgainstBackend(rq, a, finalText, backendText)
    const answerSourceDerived = hasManualOverride || hasManualDraft || hasSelectionEdit || finalDiffersFromBackend
      ? 'user'
      : 'ai'
    // Conflict resolution is always a deliberate user choice — ensure it is not misclassified
    // as a pure AI accept (which would be blocked when answer_value is null/absent).
    const answerSource =
      answerSourceDerived === 'ai' && cur.conflictResolved && hasExtractedAnswerConflicts(a)
        ? 'user'
        : answerSourceDerived
    const isEdited = answerSource === 'user'
    console.log('[Accept All]', {
      qid: qidKey,
      draftAnswer: draftAnswer || null,
      finalValue: accepted ? toDisplayAnswerText(finalValue) : finalValue,
      accepted,
      backendAnswer: a?.answer_value ?? null,
      answerSource: accepted ? answerSource : null,
      conflictFallback,
      effectiveAnswer,
      skippedReason: accepted
        ? null
        : prevQState?.[qidKey]?.userCleared === true
          ? 'user-cleared'
          : 'invalid-or-empty',
    })
    if (!accepted) continue
    if (answerSource === 'ai' && !answerRowQualifiesForPureAiAccept(a)) {
      console.log('[AcceptAll]', {
        question_id: qidKey,
        answer_value: a?.answer_value ?? null,
        accepted: false,
        reason: 'no-extracted-answer-for-ai-accept',
      })
      continue
    }

    /**
     * For AI-accepted answers, store the resolved display text of the AI answer (from row.answer_value)
     * rather than whatever `finalText` contains — which may be a raw UUID from a pre-seeded apiSelections
     * entry for an unopened section. Without this, the QuestionCard label comparison fails and the card
     * incorrectly shows "ACCEPTED EDITED RESPONSE" instead of "ACCEPTED AI RESPONSE" on first open.
     */
    const aiCommittedText = answerSource === 'ai'
      ? (toDisplayAnswerText(resolveSelectionToDisplayValue(rq, a?.answer_value)) || toDisplayAnswerText(a?.answer_value) || finalText)
      : finalText

    next[qidKey] = {
      ...cur,
      status: 'accepted',
      isAccepted: true,
      isEdited,
      override: '',
      editedAnswer: isEdited ? finalText : '',
      acceptedAnswerValue: aiCommittedText,
      answerSource,
      userCleared: false,
      complete: true,
    }
    changed++
  }

  return { next, changed }
}

export default function QAPage({ oppId, onBack, onBackToDataConnectors, onReviewSaved, isOpportunityLocked = false }) {
  const [apiOppName, setApiOppName] = useState(null)
  const sections = allSections[oppId] || []
  const apiFeatureOn = useOpportunityAnswersApi()
  const apiOid = useMemo(() => toApiOpportunityId(oppId), [oppId])
  const resolvedOppName = (apiOppName || oppId || '').trim()
  const {
    answersData: apiData,
    questionsData: apiQData,
    loading: apiBundleLoading,
    answersError: apiError,
    questionsError: apiQError,
    refetch: refetchOpportunityQa,
  } = useOpportunityQaBundle(apiOid, {
    /** Always fetch when API is on — do not tie to demoFallback (that was clearing bundle and hiding citations). */
    enabled: apiFeatureOn,
  })

  useEffect(() => {
    let cancelled = false
    setApiOppName(null)
    ;(async () => {
      try {
        const rows = await fetchOpportunityIds()
        if (cancelled) return
        const norm = toApiOpportunityId(oppId)
        const hit = rows.find(r => toApiOpportunityId(r.opportunity_id) === norm)
        if (hit?.name) setApiOppName(hit.name)
      } catch {
        /* ignore */
      }
    })()
    return () => { cancelled = true }
  }, [oppId])

  const apiLoading = apiBundleLoading
  const apiQLoading = apiBundleLoading

  const questionTextById = useMemo(() => {
    const m = {}
    for (const q of apiQData?.questions || []) {
      if (q.question_id) m[q.question_id] = q.question_text
    }
    for (const a of apiData?.answers || []) {
      const id = a.question_id
      const t = a.question_text
      if (id && t && !m[id]) m[id] = t
    }
    return m
  }, [apiQData?.questions, apiData?.answers])

  const reviewQuestions = useMemo(() => {
    if (apiData?.answers?.length) {
      const qById = new Map(
        (apiQData?.questions || [])
          .filter(q => q && q.question_id != null)
          .map(q => [String(q.question_id), q]),
      )

      return apiData.answers.map(a => {
        const qid = String(a?.question_id ?? '')
        const qMeta = qById.get(qid)
        /**
         * Merge GET /questions option lists (UUID-backed `answers[]`) into the GET /answers row
         * so picklist / multi-select can render as real options in the assist UI.
         *
         * Spread order matters: answer row should win for `answer_value`, `status`, `confidence_score`, etc.
         */
        const mergedRow = qMeta ? { ...qMeta, ...a } : a
        // Preserve non-empty option lists from GET /questions when GET /answers provides none (or empty arrays).
        if (qMeta && a && typeof a === 'object') {
          const OPTION_KEYS = [
            'answers',
            'answer_list',
            'answerList',
            'possible_answers',
            'possibleAnswers',
            'answer_options',
            'answerOptions',
            'options',
          ]
          for (const k of OPTION_KEYS) {
            const qArr = qMeta?.[k]
            const aArr = a?.[k]
            if (Array.isArray(qArr) && qArr.length > 0 && (!Array.isArray(aArr) || aArr.length === 0)) {
              mergedRow[k] = qArr
            }
          }
        }
        return opportunityAnswerRowToReviewQuestion(mergedRow, {
          questionText: questionTextById[qid],
          opportunityId: apiOid,
        })
      })
    }
    if (apiQData?.questions?.length) return apiQData.questions
    return []
  }, [apiData?.answers, apiQData?.questions, questionTextById, apiOid])

  const reviewQuestionById = useMemo(() => {
    const out = new Map()
    for (const q of reviewQuestions || []) {
      if (q?.question_id != null) out.set(String(q.question_id), q)
    }
    return out
  }, [reviewQuestions])
  const catalogQuestionById = useMemo(() => {
    const out = new Map()
    for (const q of apiQData?.questions || []) {
      if (q?.question_id != null) out.set(String(q.question_id), q)
    }
    return out
  }, [apiQData?.questions])
  /** Alias for assist row lookup (same map as GET /questions catalog). */
  const apiQuestionsById = catalogQuestionById
  const backendPendingQids = useMemo(() => {
    const s = new Set()
    for (const a of apiData?.answers || []) {
      if (String(a?.status ?? '').trim().toLowerCase() === 'pending' && a?.question_id != null) {
        s.add(String(a.question_id))
      }
    }
    return s
  }, [apiData?.answers])
  const backendNonActiveQids = useMemo(() => {
    const s = new Set()
    for (const a of apiData?.answers || []) {
      if (String(a?.status ?? '').trim().toLowerCase() !== 'active' && a?.question_id != null) {
        s.add(String(a.question_id))
      }
    }
    return s
  }, [apiData?.answers])
  const eligibleReviewQuestions = useMemo(
    () => reviewQuestions.filter(q => backendNonActiveQids.has(String(q.question_id))),
    [reviewQuestions, backendNonActiveQids],
  )
  const pendingSubmitQuestions = useMemo(
    () => reviewQuestions.filter(q => backendPendingQids.has(String(q.question_id))),
    [reviewQuestions, backendPendingQids],
  )

  const [activeSec, setActiveSec] = useState(() => {
    const first = sections.find(s => !s.isSummary)
    return first?.id || sections[0]?.id || null
  })
  const [qState, setQState] = useState(() => initQAState(oppId))
  const [searchQuery, setSearchQuery] = useState('')
  const [answerFilter, setAnswerFilter] = useState('all')
  const [submitNotice, setSubmitNotice] = useState(null)
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false)
  const [showSubmitSuccess, setShowSubmitSuccess] = useState(false)
  const [submitBusy, setSubmitBusy] = useState(false)
  const [saveBusy, setSaveBusy] = useState(false)
  const [pressedFooterAction, setPressedFooterAction] = useState(null)
  const [submitError, setSubmitError] = useState(null)
  const [saveToast, setSaveToast] = useState(null)
  /** @type {[Record<string, string|string[]>, Function]} */
  const [apiSelections, setApiSelections] = useState(() => ({}))
  const [submitConfirmValidation, setSubmitConfirmValidation] = useState('')
  const [submitConfirmMissing, setSubmitConfirmMissing] = useState(() => ([]))
  const [bulkResolveOpen, setBulkResolveOpen] = useState(false)
  const [bulkResolveIncludeResolved, setBulkResolveIncludeResolved] = useState(false)
  const [bulkConflictSessionTotal, setBulkConflictSessionTotal] = useState(0)
  const [bulkConflictIndex, setBulkConflictIndex] = useState(0)
  const [showConflicts, setShowConflicts] = useState(false)
  const [resolvedConflicts, setResolvedConflicts] = useState({})
  const isSubmitting = submitBusy
  const saveToastTimerRef = useRef(null)
  const isOpportunityReadOnly = Boolean(isOpportunityLocked)

  const showSaveToast = useCallback((message, type = 'success') => {
    setSaveToast({ message: String(message ?? '').trim(), type })
    if (saveToastTimerRef.current) clearTimeout(saveToastTimerRef.current)
    saveToastTimerRef.current = setTimeout(() => setSaveToast(null), 3000)
  }, [])

  useEffect(() => {
    return () => {
      if (saveToastTimerRef.current) clearTimeout(saveToastTimerRef.current)
    }
  }, [])

  // reviewQuestionsWithAccepted: enriches each question with is_accepted flag derived from
  // qState (which is kept in sync with accepted_<oppId> in localStorage).
  // Use this list when you need to know which questions have been accepted in the current session.
  const reviewQuestionsWithAccepted = useMemo(() => {
    return reviewQuestions.map(q => {
      const qid = String(q?.question_id ?? '')
      if (!qid) return q
      const status = qState?.[qid]?.status
      return {
        ...q,
        is_accepted: status === 'accepted' || status === 'overridden',
      }
    })
  }, [reviewQuestions, qState])

  /**
   * Seed per-question review state from GET /answers once per bundle load (`oppId` reset clears the ref).
   * Local `status` is QA workflow only — never inferred from API row `active` (that flag is lifecycle/POST, not “accepted”).
   */
  const apiReviewStateSeededRef = useRef(false)

  useEffect(() => {
    apiReviewStateSeededRef.current = false
    const saved = readQaProgress(oppId)
    /** Fresh opportunity starts pending, but existing progress should be restored when available. */
    if (!saved) {
      setActiveSec(null)
      setApiSelections({})
      setQState(initQAState(oppId))
      return
    }
    setActiveSec(saved.activeSec != null ? String(saved.activeSec) : null)
    setQState(
      saved.qState && typeof saved.qState === 'object' && !Array.isArray(saved.qState)
        ? Object.fromEntries(
            Object.entries({ ...initQAState(oppId), ...saved.qState }).map(([qid, entry]) => {
              const status = String(entry?.status ?? 'pending').trim().toLowerCase()
              const normalizedAccepted = status === 'accepted' || status === 'overridden'
              const normalizedEdited =
                typeof entry?.isEdited === 'boolean'
                  ? entry.isEdited
                  : String(entry?.answerSource ?? '').trim().toLowerCase() === 'user'
              return [
                qid,
                {
                  ...DEFAULT_API_Q_STATE,
                  ...(entry || {}),
                  isAccepted: normalizedAccepted,
                  isEdited: normalizedEdited,
                },
              ]
            }),
          )
        : initQAState(oppId),
    )
    setApiSelections(
      saved.apiSelections && typeof saved.apiSelections === 'object' && !Array.isArray(saved.apiSelections)
        ? saved.apiSelections
        : {},
    )
  }, [oppId])

  useEffect(() => {
    if (!reviewQuestions.length) return
    setApiSelections(prev => {
      const next = { ...prev }
      for (const q of reviewQuestions) {
        if (Object.prototype.hasOwnProperty.call(next, q.question_id)) continue
        const opts = reviewAnswerOptions(q)
        const n = opts.length
        const conflictId = Boolean(q.conflict?.conflict_id)
        if (conflictId) {
          // For conflict rows, never seed with local/studio ids (e.g. "12"/"17").
          // Keep only backend UUID selections when present.
          if (q.final_answer_id && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(q.final_answer_id))) {
            next[q.question_id] = String(q.final_answer_id)
          }
          continue
        }
        const multi = isReviewMultiSelectMode(q, n, conflictId)
        if (multi) {
          const pre = q.selected_answer_ids ?? q.selected_answer_id_list ?? q.final_answer_ids ?? q.finalAnswerIds
          if (Array.isArray(pre) && pre.length) {
            next[q.question_id] = pre
              .map(x => {
                const s = String(x).trim()
                if (!s) return null
                return s
              })
              .filter(Boolean)
          } else if (q.final_answer_id) {
            const fa = String(q.final_answer_id)
            next[q.question_id] = [fa]
          } else next[q.question_id] = []
        } else if (q.final_answer_id) {
          const raw = String(q.final_answer_id)
          next[q.question_id] = raw
        }
      }
      if (!(apiData?.answers?.length > 0)) return next
      return applyPostIdAlignmentToSelections(
        reviewQuestions,
        next,
        apiQData?.questions ?? [],
        apiData.answers,
      )
    })
  }, [reviewQuestions, apiQData?.questions, apiData?.answers])

  // Hydrate accepted status from BOTH localStorage (accepted_<oppId>) and sessionStorage
  // (ka:sectionSave:v1:<oppId>) whenever API answers load or the opportunity changes.
  //
  // This is the authoritative restoration step that runs AFTER the API seeding effect
  // so it can correct any stale-prev race where the seeding effect received an initial
  // (pending) qState and overwrote a not-yet-committed localStorage restore.
  useEffect(() => {
    if (!apiData?.answers?.length) return

    // --- localStorage: accepted qids flag map ---
    const storedAccepted = readAcceptedAnswers(oppId)

    // --- sessionStorage: accepted entries with actual selectedAnswer values ---
    const sessionSaved = readSessionSaves(oppId)
    const sessionAnswerByQid = {}
    for (const entry of sessionSaved) {
      if (entry.status === 'accepted' && entry.question_id) {
        sessionAnswerByQid[String(entry.question_id)] = String(entry.selectedAnswer ?? '').trim()
      }
    }

    // Union: every qid marked accepted in either storage source
    const allAcceptedQids = new Set([
      ...Object.keys(storedAccepted),
      ...Object.keys(sessionAnswerByQid),
    ])
    if (!allAcceptedQids.size) return

    setQState(prev => {
      let changed = false
      const next = { ...prev }
      for (const qid of allAcceptedQids) {
        const cur = next[qid]
        const row = apiData.answers.find(a => String(a.question_id) === qid)
        // Respect explicit user undo/clear actions in this session.
        // Without this guard, a stale accepted_<oppId> snapshot can immediately
        // rehydrate the question back to accepted after Undo.
        if (cur?.userCleared === true) continue
        // For already-accepted rows: do not regress any fields, but DO repair a missing
        // conflictResolved flag (can be false when the row was persisted by an older code path
        // that didn't write this field, or when localStorage was partially cleared).
        if (cur?.status === 'accepted' || cur?.status === 'overridden' || cur?.serverLocked) {
          if (row && apiAnswerNeedsConflictClarify(row) && !cur?.conflictResolved) {
            next[qid] = { ...cur, conflictResolved: true }
            changed = true
          }
          continue
        }
        if (!row) continue
        const hasBackendConflict = apiAnswerNeedsConflictClarify(row)
        const persistedSelection = selectionRecordGet(apiSelections, qid)
        const persistedConflictAnswerId = Array.isArray(persistedSelection)
          ? String(persistedSelection[0] ?? '').trim()
          : String(persistedSelection ?? '').trim()
        // Prefer the explicitly saved answer from sessionStorage, then fall back to
        // whatever the current qState draft or backend value has.
        const sessionAnswer = sessionAnswerByQid[qid] || ''
        const fallbackValue = String(
          sessionAnswer || cur?.acceptedAnswerValue || cur?.editedAnswer || cur?.override || row.answer_value || '',
        ).trim()
        /**
         * If this question is in the accepted map it was previously accepted via acceptQ.
         * acceptQ always sets conflictResolved=true for conflict rows, so it is safe to restore
         * that flag here when we have no other evidence (storage may have been partially cleared).
         * Collect the best available conflict branch id from multiple sources.
         */
        const pinnedCaid =
          String(cur?.conflictAnswerId ?? '').trim() ||
          persistedConflictAnswerId ||
          String(row?.answer_id ?? '').trim() ||
          // Last resort: first substantive conflict option UUID from the raw row
          (() => {
            const conflicts = Array.isArray(row?.conflicts) ? row.conflicts : []
            for (const c of conflicts) {
              const id = String(c?.answer_id ?? '').trim()
              const val = String(c?.answer_value ?? c?.answer ?? c?.value ?? '').trim()
              if (id && val) return id
            }
            return null
          })() ||
          null
        next[qid] = {
          ...(cur || DEFAULT_API_Q_STATE),
          status: 'accepted',
          isAccepted: true,
          isEdited: String(cur?.answerSource ?? '').trim() === 'user',
          complete: true,
          acceptedAnswerValue: fallbackValue,
          /**
           * A question that is in the accepted map was definitely accepted via acceptQ, which
           * always sets conflictResolved=true for conflict rows. So it's safe to restore true here.
           */
          conflictResolved: hasBackendConflict ? true : Boolean(cur?.conflictResolved),
          conflictAnswerId: hasBackendConflict ? pinnedCaid : (cur?.conflictAnswerId ?? null),
          userCleared: false,
          is_accepted: true,
        }
        changed = true
      }
      return changed ? next : prev
    })
  }, [oppId, apiData?.answers, apiSelections])

  useEffect(() => {
    if (!oppId) return
    const acceptedMap = buildAcceptedMapFromState(qState)
    persistQaProgress(oppId, {
      activeSec,
      qState,
      apiSelections,
      updatedAt: Date.now(),
    })
    writeAcceptedAnswers(oppId, acceptedMap)
  }, [oppId, activeSec, qState, apiSelections])

  const persistProgressSnapshot = useCallback(() => {
    if (!oppId) return
    const acceptedMap = buildAcceptedMapFromState(qState)
    persistQaProgress(oppId, {
      activeSec,
      qState,
      apiSelections,
      updatedAt: Date.now(),
    })
    writeAcceptedAnswers(oppId, acceptedMap)
  }, [oppId, activeSec, qState, apiSelections])

  const useApiLayout =
    apiFeatureOn &&
    apiData &&
    !apiLoading &&
    !apiError &&
    (apiData.answers?.length ?? 0) > 0

  /** API mode is waiting for GET /answers — avoid mock rail, mock stats, and mock question list. */
  const apiBundlePending = apiFeatureOn && apiLoading
  /** Static `data.js` rail only when we are not showing the live API layout (see sidebar ternary order). */
  const useStaticQualificationRail = false

  /**
   * Whether Submit should call POST /opportunities/{id}/answers.
   * Do not tie this to `apiLoading`: refetch sets loading=true while prior `apiData` is still valid;
   * gating on loading caused confirm to take the demo path (no network request).
   */
  const canPostOpportunityReview =
    apiFeatureOn &&
    !apiError &&
    (apiData?.answers?.length ?? 0) > 0 &&
    eligibleReviewQuestions.length > 0

  useEffect(() => {
    console.log('[QA Data Source]', {
      answersSource: 'live API only',
      questionsSource: 'live API only',
      opportunity_id: apiOid,
      loading: apiLoading,
      hasError: Boolean(apiError),
    })
  }, [apiOid, apiLoading, apiError])

  const apiGrouped = useMemo(() => {
    if (!(apiData?.answers?.length)) return null
    try {
      return groupAnswersByQaCatalog(apiData.answers)
    } catch (error) {
      console.error('[QA Grouping Error]', {
        error: error instanceof Error ? error.message : String(error),
      })
      return {
        sections: [],
        uncategorized: Array.isArray(apiData.answers) ? apiData.answers : [],
      }
    }
  }, [apiData?.answers])
  const apiQuestionCardModelsById = useMemo(() => {
    const out = new Map()
    for (const a of apiData?.answers || []) {
      out.set(a.question_id, buildQuestionCardModelFromApiAnswer(a, questionTextById[a.question_id]))
    }
    return out
  }, [apiData?.answers, questionTextById])

  const reviewSectionOrder = useMemo(() => {
    if (useApiLayout && apiGrouped) {
      const ids = []
      for (const s of apiGrouped.sections) {
        const n = s.subsections.reduce((acc, sub) => acc + sub.answers.length, 0)
        if (n > 0) ids.push(s.id)
      }
      if (apiGrouped.uncategorized.length > 0) ids.push('uncategorized')
      return ids
    }
    if (useStaticQualificationRail) {
      return sections.filter(s => !s.isSummary).map(s => s.id)
    }
    return []
  }, [useApiLayout, apiGrouped, useStaticQualificationRail, sections])

  const activeSectionIdx = activeSec != null ? reviewSectionOrder.indexOf(activeSec) : -1
  const isLastReviewSection =
    reviewSectionOrder.length > 0 && activeSectionIdx === reviewSectionOrder.length - 1
  const hasNextReviewSection =
    activeSectionIdx >= 0 && activeSectionIdx < reviewSectionOrder.length - 1
  const showSectionNav =
    reviewSectionOrder.length > 0 && (useApiLayout || useStaticQualificationRail)

  const handleSaveNextSection = useCallback(() => {
    if (!hasNextReviewSection) return
    const nextIndex = activeSectionIdx + 1
    if (nextIndex < 0 || nextIndex >= reviewSectionOrder.length) return
    const nextSectionId = reviewSectionOrder[nextIndex]
    const totalQuestionsInNextSection = (() => {
      if (useApiLayout && apiGrouped) {
        if (nextSectionId === 'uncategorized') return Array.isArray(apiGrouped.uncategorized) ? apiGrouped.uncategorized.length : 0
        const sec = (apiGrouped.sections || []).find(s => s.id === nextSectionId)
        if (!sec) return 0
        return (sec.subsections || []).reduce((n, sub) => n + (Array.isArray(sub.answers) ? sub.answers.length : 0), 0)
      }
      const sec = (sections || []).find(s => s.id === nextSectionId)
      if (!sec) return 0
      return (sec.signals || [])
        .filter(sig => sig?.type === 'ai')
        .reduce((n, sig) => n + (Array.isArray(sig?.qs) ? sig.qs.length : 0), 0)
    })()
    console.log('[Section Change]', {
      currentSectionId: activeSec,
      nextSectionId,
      totalQuestionsInNextSection,
    })
    setActiveSec(nextSectionId)
  }, [hasNextReviewSection, activeSectionIdx, reviewSectionOrder, useApiLayout, apiGrouped, sections, activeSec])

  const predefinedQs = useMemo(() => {
    if (apiBundlePending) return []
    if (apiFeatureOn && apiData?.answers?.length) {
      return apiData.answers.map(a => {
        const p = placementForQuestionId(a.question_id)
        const qt = (questionTextById[a.question_id] || a.question_text || '').trim()
        const id = a.question_id
        const sectionTitle = p ? `${p.sectionTitle} · ${p.subsection}` : 'Other'
        const searchHay = `${id} ${qt} ${a.answer_value || ''} ${sectionTitle}`.toLowerCase()
        return {
          id,
          text: qt || String(id),
          sectionId: p?.sectionId ?? 'uncategorized',
          sectionTitle,
          searchHay,
        }
      })
    }
    return []
  }, [apiBundlePending, apiFeatureOn, apiData, oppId, questionTextById])
  const filteredPredefinedQs = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return predefinedQs.filter(item => {
      const hay = item.searchHay ?? `${item.text} ${item.sectionTitle}`.toLowerCase()
      return !q || hay.includes(q)
    })
  }, [predefinedQs, searchQuery])

  const showQuestionResults = Boolean(searchQuery.trim())

  const navigateToSearchQuestion = useCallback(
    item => {
      setActiveSec(item.sectionId)
      if (useApiLayout) {
        requestAnimationFrame(() => {
          document.getElementById(apiAnswerElementId(item.id))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
      }
    },
    [useApiLayout],
  )

  const showOpportunityQuestionSearch =
    (useApiLayout || useStaticQualificationRail) && predefinedQs.length > 0 && !apiBundlePending

  const updateQ = useCallback((qid, patch) => {
    setQState(prev => ({
      ...prev,
      [qid]: { ...(prev[qid] || DEFAULT_API_Q_STATE), ...patch },
    }))
  }, [])
  const updateQDraft = useCallback((qid, value) => {
    const text = String(value ?? '').trim()
    const qidKey = String(qid)
    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)
    const backendDisplay = String(
      resolveSelectionToDisplayValue(rq, row?.answer_value ?? row?.answer ?? '') || getConflictFallbackAnswerFromRow(row),
    ).trim()
    const draftIsOverride =
      text !== '' &&
      (backendDisplay === '' || isOverrideAgainstBackend(rq, row, text, backendDisplay))
    setQState(prev => {
      const cur = prev[qid] || DEFAULT_API_Q_STATE
      // Fix Part 4: do NOT overwrite accepted/overridden state with a draft value.
      // The MCQ draft-sync effect in QuestionCard fires even after accept, which would
      // set answerSource='user' and corrupt the label to "ACCEPTED EDITED RESPONSE".
      if (cur.status === 'accepted' || cur.status === 'overridden') {
        return prev
      }
      const next = {
        ...cur,
        editedAnswer: value ?? '',
        answerSource: text ? (draftIsOverride ? 'user' : 'ai') : 'ai',
        isAccepted: false,
        isEdited: text ? draftIsOverride : false,
        complete: isValidAnswer(text),
        status: cur.status || 'pending',
      }
      console.log('[Manual Edit Sync]', {
        qid,
        editedAnswer: next.editedAnswer,
      })
      return { ...prev, [qid]: next }
    })
  }, [apiData?.answers, reviewQuestions])

  const setAlignedApiSelection = useCallback((qid, nextSel) => {
    setApiSelections(prev => {
      const next = { ...prev, [qid]: nextSel }
      if (!reviewQuestions.length) return next
      if (!apiData?.answers?.length) return next
      return applyPostIdAlignmentToSelections(
        reviewQuestions,
        next,
        apiQData?.questions ?? [],
        apiData.answers,
      )
    })
  }, [reviewQuestions, apiData?.answers, apiQData?.questions])

  const acceptQ = useCallback((qid, extra) => {
    const qidKey = String(qid)
    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    if (isBackendAnswerActive(row)) return
    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)

    const manualValueFromExtra =
      typeof extra === 'string'
        ? String(extra).trim()
        : String(extra?.manualValue ?? '').trim()

    const hasAssistSelection = Boolean(
      typeof extra === 'object' && extra != null && extra?.assistSelection?.mode === 'pick'
        ? (() => {
            const normalized = normalizePickSelectionPayload(rq, extra?.assistSelection?.pick)
            return Boolean(normalized.answer_id || normalized.answer_value)
          })()
        : typeof extra === 'object' && extra != null && Array.isArray(extra?.assistSelection?.multi) &&
            extra?.assistSelection?.multi?.some(x => String(x ?? '').trim() !== ''),
    )

    // Resolve selection side-effects (apiSelections) outside of setQState
    let selectedValueForApi = selectionRecordGet(apiSelections, qid)
    let selectedLabel = ''

    if (typeof extra === 'object' && extra?.assistSelection) {
      const { mode, pick, multi } = extra.assistSelection
      if (mode === 'multi') {
        const ids = Array.isArray(multi) ? multi.filter(x => x != null && String(x).trim() !== '') : []
        if (ids.length > 0) {
          selectedLabel = ids
            .map(id => getAnswerLabelFromSelection(rq, id))
            .map(v => String(v ?? '').trim())
            .filter(Boolean)
            .join(', ')
          if (selectedLabel) {
            setAlignedApiSelection(qid, [...ids])
            selectedValueForApi = [...ids]
          }
        }
      } else if (mode === 'pick') {
        const normalizedPick = normalizePickSelectionPayload(rq, pick)
        if (normalizedPick.answer_id || normalizedPick.answer_value) {
          selectedLabel = normalizedPick.answer_value || getAnswerLabelFromSelection(rq, normalizedPick.answer_id)
          const apiValue = normalizedPick.answer_id || normalizedPick.answer_value
          setAlignedApiSelection(qid, apiValue)
          selectedValueForApi = apiValue
        }
      }
    }

    // Use functional state update to avoid stale qState closure
    setQState(prev => {
      const current = prev[qidKey] || DEFAULT_API_Q_STATE
      if (current.serverLocked) return prev

      const hasManualEdited = String(current.editedAnswer ?? '').trim() !== ''
      const hasManualOverride = String(current.override ?? '').trim() !== ''
      const canAutoResolveConflict = hasManualEdited || hasManualOverride || hasAssistSelection || manualValueFromExtra !== ''

      if (row && apiAnswerNeedsConflictClarify(row) && !current.conflictResolved && !canAutoResolveConflict) {
        console.log('[Manual Accept blocked]', {
          qid: qidKey,
          reason: 'conflict-unresolved-without-user-input',
          manualValueFromExtra,
        })
        return prev
      }

      const { effectiveAnswer, conflictFallback } = getEffectiveDisplayAnswer({
        question: rq,
        row,
        qStateEntry: current,
        selectionValue: selectedValueForApi,
      })

      // Priority: manualValue from QuestionCard > selectedLabel from MCQ > effectiveAnswer
      const finalValue = manualValueFromExtra || selectedLabel || effectiveAnswer

      if (!isValidAnswer(finalValue)) {
        console.log('[Manual Accept blocked]', {
          qid: qidKey,
          reason: 'invalid-final-value',
          manualValueFromExtra,
          selectedLabel,
          effectiveAnswer,
        })
        return prev
      }

      const finalAnswerText = toDisplayAnswerText(finalValue)
      const backendAnswerText = toDisplayAnswerText(
        resolveSelectionToDisplayValue(rq, row?.answer_value),
      )
      // QuestionCard sends `manualValue` only when user actually changed the AI recommendation.
      // Pure "accept current AI selection" should stay AI even if display formatting differs.
      const acceptFromUneditedAssistSelection =
        hasAssistSelection &&
        manualValueFromExtra === '' &&
        !hasManualEdited &&
        !hasManualOverride
      const hasManualValue =
        manualValueFromExtra !== ''
      // For structured accept without manual text, compute source from current selection
      // vs AI only, and ignore previous override/draft flags.
      const selectionOnlyComparison =
        hasAssistSelection &&
        manualValueFromExtra === ''
      const effectiveHasManualOverride = selectionOnlyComparison ? false : hasManualOverride
      const hasManualSelection =
        !acceptFromUneditedAssistSelection &&
        selectedLabel !== '' &&
        isOverrideAgainstBackend(rq, row, selectedLabel, backendAnswerText)
      const hasManualDraft =
        !selectionOnlyComparison &&
        String(current.editedAnswer ?? '').trim() !== '' &&
        !acceptFromUneditedAssistSelection &&
        isOverrideAgainstBackend(rq, row, current.editedAnswer, backendAnswerText)
      const finalDiffersFromBackend =
        finalAnswerText !== '' &&
        !acceptFromUneditedAssistSelection &&
        isOverrideAgainstBackend(rq, row, finalAnswerText, backendAnswerText)
      const answerSourceDerived =
        effectiveHasManualOverride || hasManualValue || hasManualSelection || hasManualDraft || finalDiffersFromBackend
          ? 'user'
          : 'ai'
      // Conflict resolution is always a deliberate user choice — even when the selected conflict
      // option happens to match an AI candidate (it always will, since all options come from the
      // conflicts[] array). Without this, accepting a conflict-resolved answer where answer_value
      // is null gets silently blocked by the ai-accept qualification guard below.
      const answerSource =
        answerSourceDerived === 'ai' && current.conflictResolved && hasExtractedAnswerConflicts(row)
          ? 'user'
          : answerSourceDerived

      if (answerSource === 'ai' && !answerRowQualifiesForPureAiAccept(row)) {
        console.log('[Manual Accept blocked]', {
          qid: qidKey,
          reason: 'no-extracted-answer-for-ai-accept',
        })
        return prev
      }

      console.log('[Single Accept]', {
        qid: qidKey,
        finalAnswer: finalAnswerText,
        source: manualValueFromExtra ? 'manualValue' : selectedLabel ? 'selectedLabel' : 'effectiveAnswer',
        answerSource,
        backendAnswer: backendAnswerText,
        prevState: current,
      })
      console.log('[Answer Source]', {
        qid: qidKey,
        backendAnswer: backendAnswerText,
        editedAnswer: current.editedAnswer ?? null,
        answerSource,
        status: 'accepted',
      })

      if (!isValidAnswer(finalAnswerText)) return prev
      return {
        ...prev,
        [qidKey]: {
          ...current,
          // Persist accepted value in acceptedAnswerValue; keep editedAnswer only for true user edits.
          editedAnswer: answerSource === 'user' ? finalAnswerText : '',
          acceptedAnswerValue: finalAnswerText,
          answerSource,
          status: 'accepted',
          isAccepted: true,
          isEdited: answerSource === 'user',
          complete: true,
          override: '',
          conflictResolved: row && apiAnswerNeedsConflictClarify(row) ? true : current.conflictResolved,
          userCleared: false,
        },
      }
    })
  }, [apiData?.answers, reviewQuestions, apiSelections, setAlignedApiSelection])
  const undoQ = (qid) => {
    const qidKey = String(qid)
    const current = qState[qidKey] || DEFAULT_API_Q_STATE
    if (current?.serverLocked) return

    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    const hasPureAiAnswer = answerRowQualifiesForPureAiAccept(row)
    const restoredDraftValue = String(
      current.editedAnswer || current.acceptedAnswerValue || current.override || '',
    ).trim()
    const restoredAnswerSource =
      restoredDraftValue && !hasPureAiAnswer
        ? 'user'
        : (String(current.answerSource ?? '').trim() || 'ai')

    updateQ(qid, {
      status: 'pending',
      isAccepted: false,
      isEdited: false,
      override: '',
      editedAnswer: restoredDraftValue,
      acceptedAnswerValue: '',
      answerSource: restoredAnswerSource,
      userCleared: true,
      conflictResolved: current.conflictResolved,
      conflictAnswerId: current.conflictAnswerId ?? null,
    })
  }
  const saveOverride = (qid, text) => {
    if (qState[qid]?.serverLocked) return
    const t = String(text || '').trim()
    if (!t) {
      updateQ(qid, { status: 'pending', isAccepted: false, isEdited: false, override: '', editedAnswer: '', acceptedAnswerValue: '', answerSource: 'ai', userCleared: true })
      return
    }
    const qidKey = String(qid)
    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)
    const backendDisplay = String(
      resolveSelectionToDisplayValue(rq, row?.answer_value ?? row?.answer ?? '') || getConflictFallbackAnswerFromRow(row),
    ).trim()
    const overrideMatchesBackend =
      backendDisplay !== '' &&
      !isOverrideAgainstBackend(rq, row, t, backendDisplay)
    updateQ(
      qid,
      overrideMatchesBackend
        ? { status: 'accepted', isAccepted: true, isEdited: false, override: '', editedAnswer: '', acceptedAnswerValue: backendDisplay || t, answerSource: 'ai', userCleared: false }
        : { status: 'overridden', isAccepted: true, isEdited: true, override: text, editedAnswer: text, acceptedAnswerValue: t, answerSource: 'user', userCleared: false },
    )
    /**
     * Conflict override: keep apiSelections pinned to the resolved conflict branch id
     * (so POST can send conflict_answer_id), while override_value carries the user-chosen label.
     */
    const pinned = String(qState?.[qid]?.conflictAnswerId ?? '').trim()
    if (pinned) {
      setAlignedApiSelection(qid, pinned)
    } else if (t) {
      setAlignedApiSelection(qid, t)
    }
  }
  const editOverride = (qid) => {
    if (qState[qid]?.serverLocked) return
    updateQ(qid, { status: 'pending', isAccepted: false, acceptedAnswerValue: '' })
  }
  const saveEdit = (qid, text) => {
    if (qState[qid]?.serverLocked) return
    const qidKey = String(qid)
    if (apiData?.answers?.length) {
      const row = apiData.answers.find(a => a.question_id === qid)
      if (isBackendAnswerActive(row)) return
      if (row && apiAnswerNeedsConflictClarify(row) && !qState[qid]?.conflictResolved) return
    }
    const t = String(text || '').trim()
    if (!t) {
      updateQ(qid, { editedAnswer: '', override: '', acceptedAnswerValue: '', status: 'pending', isAccepted: false, isEdited: false, answerSource: 'ai', userCleared: true })
      return
    }
    /**
     * Save changes should NOT auto-accept:
     * keep user text as a pending draft until the reviewer explicitly clicks Accept.
     */
    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)
    const backendDisplay = String(
      resolveSelectionToDisplayValue(rq, row?.answer_value ?? row?.answer ?? '') || getConflictFallbackAnswerFromRow(row),
    ).trim()
    updateQ(qid, {
      editedAnswer: text,
      acceptedAnswerValue: '',
      isAccepted: false,
      isEdited: true,
      answerSource: 'user',
      status: 'pending',
      userCleared: false,
    })
    if (t) setAlignedApiSelection(qid, t)
  }
  const saveFeedback = (qid, vote, text) => {
    if (qState[qid]?.serverLocked) return
    const existing = qState[qid]?.feedback
    if (existing != null && existing !== '') return
    updateQ(qid, { feedback: vote, feedbackText: text || '' })
  }
  const resolveConflict = (qid, chosen) => {
    if (qState[qid]?.serverLocked) return
    const qidKey = String(qid)
    const isObj = chosen != null && typeof chosen === 'object' && !Array.isArray(chosen)
    const text = isObj ? String(chosen.answer ?? '').trim() : String(chosen ?? '').trim()
    const row = apiData?.answers?.find(a => String(a.question_id) === qidKey)
    const rq = reviewQuestions.find(r => String(r.question_id) === qidKey)
    let id =
      isObj && chosen.answer_id != null && String(chosen.answer_id).trim() !== ''
        ? String(chosen.answer_id).trim()
        : null
    if (!id && text) {
      if (rq) {
        const opts = reviewAnswerOptions(rq)
        const hit = opts.find(
          o =>
            String(o.id ?? '').trim() === text ||
            normalizeConflictCompareText(o?.text) === normalizeConflictCompareText(text),
        )
        if (hit) id = String(hit.id)
      }
    }
    if (!id) {
      id = resolveConflictSelectionIdFromRow(row, chosen, text)
    }
    const backendDisplay = String(
      resolveSelectionToDisplayValue(rq, row?.answer_value ?? row?.answer ?? '') || getConflictFallbackAnswerFromRow(row),
    ).trim()
    const selectedFromConflictOptions = isObj
    const answerSource = selectedFromConflictOptions
      ? 'ai'
      : (
          text && isOverrideAgainstBackend(rq, row, text, backendDisplay)
            ? 'user'
            : 'ai'
        )
    // Picking a conflict option should only set the draft answer; acceptance is explicit (Accept / Accept all).
    updateQ(qid, {
      editedAnswer: text,
      isAccepted: false,
      isEdited: answerSource === 'user',
      answerSource,
      conflictResolved: true,
      conflictAnswerId: id,
      status: 'pending',
      userCleared: false,
      override: '',
    })
    if (id) setAlignedApiSelection(qid, id)
    else if (text) setAlignedApiSelection(qid, text)
  }

  const handleAssistSelectionDraft = useCallback((qid, draft) => {
    if (!draft) return
    setApiSelections(prev => {
      const st = String(qState[String(qid)]?.status ?? '').trim().toLowerCase()
      // Do not churn selection state for finalized cards; this causes visible
      // accept/undo jitter when child effects emit stale draft snapshots.
      if (st === 'accepted' || st === 'overridden') return prev
      const nextMulti = draft.mode === 'multi'
        ? (Array.isArray(draft.value) ? [...draft.value] : [])
        : null
      const nextPick = draft.mode !== 'multi'
        ? (draft.value != null ? String(draft.value) : '')
        : null
      const cur = prev[qid]
      if (draft.mode === 'multi' && nextMulti) {
        const a = Array.isArray(cur) ? cur : []
        if (a.length === nextMulti.length && a.every((v, i) => String(v) === String(nextMulti[i]))) return prev
        return { ...prev, [qid]: nextMulti }
      }
      if (nextPick != null && String(cur ?? '') === nextPick) return prev
      return { ...prev, [qid]: nextPick ?? '' }
    })
  }, [qState])

  const apiUnresolvedConflictCount = useMemo(() => {
    if (!useApiLayout || !apiData?.answers?.length) return 0
    return apiData.answers.filter(
      a => apiAnswerNeedsConflictClarify(a) && !qState[String(a.question_id)]?.conflictResolved,
    ).length
  }, [useApiLayout, apiData?.answers, qState])
  const apiEditableConflictCount = useMemo(() => {
    if (!useApiLayout || !apiData?.answers?.length) return 0
    return apiData.answers.filter(a => {
      const qid = String(a.question_id)
      return apiAnswerNeedsConflictClarify(a) && !qState[qid]?.serverLocked
    }).length
  }, [useApiLayout, apiData?.answers, qState])

  const demoUnresolvedConflictCount = useMemo(() => {
    if (useApiLayout) return 0
    let n = 0
    sections.forEach(sec => {
      if (sec.isSummary) return
      sec.signals.forEach(sig => {
        if (sig.type !== 'ai') return
        sig.qs.forEach(q => {
          if ((q.conflicts?.length ?? 0) >= 2 && !qState[q.id]?.conflictResolved) n++
        })
      })
    })
    return n
  }, [useApiLayout, sections, qState])
  const demoEditableConflictCount = useMemo(() => {
    if (useApiLayout) return 0
    let n = 0
    sections.forEach(sec => {
      if (sec.isSummary) return
      sec.signals.forEach(sig => {
        if (sig.type !== 'ai') return
        sig.qs.forEach(q => {
          if ((q.conflicts?.length ?? 0) >= 2 && !qState[q.id]?.serverLocked) n++
        })
      })
    })
    return n
  }, [useApiLayout, sections, qState])

  /**
   * Rows that still need conflict clarification (same as left rail + `openBulkResolve`).
   * `unresolvedConflicts` (submit stats) only counts API rows with status `pending`, so it can be 0
   * while conflict questions with status `active` (etc.) still show as open — that wrongly disabled Resolve.
   */
  const bulkResolveConflictCount = useMemo(
    () => (useApiLayout ? apiEditableConflictCount : demoEditableConflictCount),
    [useApiLayout, apiEditableConflictCount, demoEditableConflictCount],
  )

  const conflictedQuestions = useMemo(
    () =>
      (apiData?.answers || []).filter(
        a =>
          (Array.isArray(a.conflicts) && a.conflicts.length > 0) ||
          a.conflict_id != null,
      ),
    [apiData?.answers],
  )

  const handleResolveConflicts = useCallback(() => {
    if (isOpportunityReadOnly) return
    setShowConflicts(true)
  }, [isOpportunityReadOnly])

  const handleSelectConflict = useCallback((qid, value) => {
    setResolvedConflicts(prev => ({
      ...prev,
      [qid]: value,
    }))
  }, [])

  const applyResolvedConflicts = useCallback(() => {
    if (isOpportunityReadOnly) return
    for (const a of conflictedQuestions) {
      const qid = a.question_id
      const selected = resolvedConflicts[qid]
      if (!selected) continue
      resolveConflict(qid, selected)
    }
    setShowConflicts(false)
  }, [conflictedQuestions, resolvedConflicts, resolveConflict, isOpportunityReadOnly])

  /** Resolved vs total questions that require conflict clarification (for Resolve conflicts button bar). */
  const conflictResolutionProgress = useMemo(() => {
    if (useApiLayout && apiData?.answers?.length) {
      const rows = apiData.answers.filter(a => apiAnswerNeedsConflictClarify(a))
      const total = rows.length
      if (!total) return { pct: 0, resolved: 0, total: 0 }
      const resolved = rows.filter(a => qState[String(a.question_id)]?.conflictResolved).length
      return { pct: resolved / total, resolved, total }
    }
    const ids = []
    sections.forEach(sec => {
      if (sec.isSummary) return
      sec.signals.forEach(sig => {
        if (sig.type !== 'ai') return
        sig.qs.forEach(q => {
          if ((q.conflicts?.length ?? 0) >= 2) ids.push(q.id)
        })
      })
    })
    const total = ids.length
    if (!total) return { pct: 0, resolved: 0, total: 0 }
    const resolved = ids.filter(id => qState[id]?.conflictResolved).length
    return { pct: resolved / total, resolved, total }
  }, [useApiLayout, apiData?.answers, sections, qState])

  const bulkConflictCandidates = useMemo(() => {
    if (!bulkResolveOpen) return []
    if (useApiLayout && apiData?.answers?.length) {
      return apiData.answers
        .filter(
          a =>
            apiAnswerNeedsConflictClarify(a) &&
            !qState[String(a.question_id)]?.serverLocked &&
            (bulkResolveIncludeResolved || !qState[String(a.question_id)]?.conflictResolved),
        )
        .map(a => ({
          qid: String(a.question_id),
          qModel: buildQuestionCardModelFromApiAnswer(a, questionTextById[a.question_id]),
        }))
    }
    if (!useApiLayout) {
      const out = []
      for (const sec of sections) {
        if (sec.isSummary) continue
        for (const sig of sec.signals) {
          if (sig.type !== 'ai' || !sig.qs) continue
          sig.qs.forEach(q => {
            if (
              (q.conflicts?.length ?? 0) >= 2 &&
              !qState[q.id]?.serverLocked &&
              (bulkResolveIncludeResolved || !qState[q.id]?.conflictResolved)
            ) {
              out.push({ qid: String(q.id), qModel: q })
            }
          })
        }
      }
      return out
    }
    return []
  }, [bulkResolveOpen, bulkResolveIncludeResolved, useApiLayout, apiData?.answers, qState, questionTextById, sections])

  const bulkConflictPresentation = useMemo(() => {
    if (!bulkConflictCandidates.length) return null
    const idx = Math.min(Math.max(0, bulkConflictIndex), bulkConflictCandidates.length - 1)
    return bulkConflictCandidates[idx]
  }, [bulkConflictCandidates, bulkConflictIndex])

  const bulkStepLabel = useMemo(() => {
    if (!bulkResolveOpen || bulkConflictCandidates.length === 0) return null
    return `${Math.min(bulkConflictIndex + 1, bulkConflictCandidates.length)} of ${bulkConflictCandidates.length}`
  }, [
    bulkResolveOpen,
    bulkConflictCandidates.length,
    bulkConflictIndex,
  ])

  const openBulkResolve = useCallback(() => {
    if (isOpportunityReadOnly) return
    const unresolved = useApiLayout ? apiUnresolvedConflictCount : demoUnresolvedConflictCount
    const editable = useApiLayout ? apiEditableConflictCount : demoEditableConflictCount
    if (editable === 0) return
    setBulkResolveIncludeResolved(unresolved === 0)
    setBulkConflictSessionTotal(unresolved > 0 ? unresolved : editable)
    setBulkConflictIndex(0)
    setBulkResolveOpen(true)
  }, [useApiLayout, apiUnresolvedConflictCount, demoUnresolvedConflictCount, apiEditableConflictCount, demoEditableConflictCount, isOpportunityReadOnly])

  useEffect(() => {
    if (!bulkResolveOpen) return
    if (!bulkConflictCandidates.length) {
      setBulkResolveOpen(false)
      setBulkResolveIncludeResolved(false)
      setBulkConflictSessionTotal(0)
      setBulkConflictIndex(0)
    }
    if (bulkConflictIndex >= bulkConflictCandidates.length && bulkConflictCandidates.length > 0) {
      setBulkConflictIndex(bulkConflictCandidates.length - 1)
    }
  }, [bulkResolveOpen, bulkConflictCandidates, bulkConflictIndex])

  const mergedSelectionsForSubmit = useMemo(
    () =>
      useApiLayout && pendingSubmitQuestions.length > 0 && (apiData?.answers?.length ?? 0) > 0
        ? mergeApiSelectionsForSubmit(pendingSubmitQuestions, apiSelections, apiData.answers, qState, {
            questionsCatalog: apiQData?.questions || [],
          })
        : null,
    [useApiLayout, pendingSubmitQuestions, apiSelections, apiData?.answers, apiQData?.questions, qState],
  )

  const reviewSelectionsValid = useMemo(() => {
    if (!useApiLayout || !mergedSelectionsForSubmit) return true
    return validateReviewSelectionsForSubmit(pendingSubmitQuestions, mergedSelectionsForSubmit, qState, {
      opportunityId: apiOid,
      rawAnswerRows: apiData?.answers || [],
    }).ok
  }, [useApiLayout, pendingSubmitQuestions, mergedSelectionsForSubmit, qState, apiOid, apiData?.answers])

  const requiredReviewOk = useMemo(() => {
    if (!useApiLayout || !mergedSelectionsForSubmit) return true
    return validateRequiredReviewQuestions(pendingSubmitQuestions, mergedSelectionsForSubmit, qState, {
      rawAnswerRows: apiData?.answers || [],
    }).ok
  }, [useApiLayout, pendingSubmitQuestions, mergedSelectionsForSubmit, qState, apiData?.answers])

  const { totalQ, answeredQ, unresolvedConflicts, submitReady, pendingFinalize } = useMemo(() => {
    let tq = 0
    let aq = 0
    let finalized = 0
    let submitTq = 0
    let submitFinalized = 0
    let submitUc = 0

    if (apiBundlePending) {
      return { totalQ: 0, answeredQ: 0, unresolvedConflicts: 0, submitReady: false, pendingFinalize: 0 }
    }
    if (apiFeatureOn && apiData?.answers?.length && useApiLayout) {
      for (const a of apiData.answers) {
        const qid = String(a.question_id)
        tq++
        const st = qState[qid]?.status ?? 'pending'
        const serverLocked = isQuestionServerLocked(a, qState[qid])
        if (st !== 'pending' || serverLocked) aq++
        if (st === 'accepted' || st === 'overridden' || serverLocked) finalized++
        if (!backendPendingQids.has(qid)) continue
        submitTq++
        if (st === 'accepted' || st === 'overridden' || serverLocked) submitFinalized++
        if (apiAnswerNeedsConflictClarify(a) && !qState[qid]?.conflictResolved) submitUc++
      }
      const ready = submitTq > 0 && submitUc === 0 && submitFinalized === submitTq
      return {
        totalQ: tq,
        answeredQ: aq,
        unresolvedConflicts: submitUc,
        submitReady: ready,
        pendingFinalize: submitTq - submitFinalized,
      }
    }
    let uc = 0
    if (useStaticQualificationRail) {
      sections.forEach(sec => sec.signals.forEach(sig => {
        if (sig.type !== 'ai') return
        sig.qs.forEach(q => {
          tq++
          const st = qState[q.id]?.status ?? 'pending'
          const serverLocked = isQuestionServerLocked(q, qState[q.id])
          if (st !== 'pending' || serverLocked) aq++
          if (st === 'accepted' || st === 'overridden' || serverLocked) finalized++
          if (q.conflicts?.length >= 2 && !qState[q.id]?.conflictResolved) uc++
        })
      }))
      const ready = tq > 0 && uc === 0 && finalized === tq
      return {
        totalQ: tq,
        answeredQ: aq,
        unresolvedConflicts: uc,
        submitReady: ready,
        pendingFinalize: tq - finalized,
      }
    }
    return { totalQ: 0, answeredQ: 0, unresolvedConflicts: 0, submitReady: false, pendingFinalize: 0 }
  }, [
    apiBundlePending,
    apiFeatureOn,
    apiData?.answers,
    useApiLayout,
    useStaticQualificationRail,
    sections,
    qState,
    backendPendingQids,
  ])

  const allQuestionsForCompletion = useMemo(() => {
    if (useApiLayout) return reviewQuestions
    return sections
      .filter(sec => !sec.isSummary)
      .flatMap(sec => sec.signals.filter(sig => sig.type === 'ai').flatMap(sig => sig.qs))
  }, [useApiLayout, reviewQuestions, sections])

  const { allQuestionsComplete, incompleteQuestions } = useMemo(() => {
    const missing = []
    for (const q of allQuestionsForCompletion) {
      const qid = questionCompletionKey(q)
      if (!qid) continue
      const complete = isQuestionComplete(
        q,
        qState?.[qid],
      )
      if (!complete) missing.push(qid)
    }
    return { allQuestionsComplete: missing.length === 0 && allQuestionsForCompletion.length > 0, incompleteQuestions: missing }
  }, [allQuestionsForCompletion, qState])

  const currentSectionQuestionsForCompletion = useMemo(() => {
    if (useApiLayout && apiGrouped) {
      if (activeSec === 'uncategorized') return apiGrouped.uncategorized
      const active = apiGrouped.sections.find(s => s.id === activeSec)
      return active ? active.subsections.flatMap(sub => sub.answers) : []
    }
    const activeSection = sections.find(s => s.id === activeSec)
    return activeSection
      ? activeSection.signals.filter(s => s.type === 'ai').flatMap(s => s.qs)
      : []
  }, [useApiLayout, apiGrouped, activeSec, sections])

  const { sectionComplete, pendingSectionQids } = useMemo(() => {
    const pending = []
    for (const q of currentSectionQuestionsForCompletion) {
      const qid = questionCompletionKey(q)
      if (!qid) continue
      const complete = isQuestionComplete(
        q,
        qState?.[qid],
      )
      if (!complete) pending.push(qid)
    }
    return { sectionComplete: pending.length === 0 && currentSectionQuestionsForCompletion.length > 0, pendingSectionQids: pending }
  }, [currentSectionQuestionsForCompletion, qState])

  useEffect(() => {
    console.log('[Submit Button State]', {
      allQuestionsComplete,
      incompleteQuestions,
    })
  }, [allQuestionsComplete, incompleteQuestions])

  useEffect(() => {
    console.log('[SaveNext State]', {
      sectionId: activeSec,
      sectionComplete,
      pendingQids: pendingSectionQids,
    })
  }, [activeSec, sectionComplete, pendingSectionQids])

  const handleAcceptAll = useCallback(() => {
    if (isOpportunityReadOnly) return
    if (apiFeatureOn && apiData?.answers?.length && useApiLayout) {
      console.log('[Accept All Start]', {
        totalQuestions: apiData?.answers?.length ?? 0,
        qStateSnapshot: qState,
      })
      console.log('[Accept All] all answers received:', apiData.answers)
      let changed = 0
      let nextQState = qState
      const acceptedValues = []
      setQState(prev => {
        const { next, changed: changedCount } = applyAcceptAllToQState(prev, {
          apiAnswers: apiData.answers,
          reviewQuestions,
          apiQuestionCardModelsById,
          apiSelections,
          questionsCatalog: apiQData?.questions || [],
        })
        changed = changedCount
        nextQState = next
        const seenQids = new Set()
        for (const a of apiData.answers) {
          const qidKey = String(a.question_id)
          if (seenQids.has(qidKey)) continue
          seenQids.add(qidKey)
          const before = prev[qidKey]?.status ?? 'pending'
          const after = next[qidKey]?.status ?? 'pending'
          if (before === 'pending' && after === 'accepted') {
            acceptedValues.push({
              question_id: qidKey,
              value: String(next[qidKey]?.editedAnswer ?? '').trim(),
            })
          }
        }
        console.log('[Accept All Final State]', next)
        return next
      })
      console.log('[Accept All] final value(s) being accepted:', acceptedValues)
      if (changed === 0) {
        setSubmitNotice(
          'Nothing new to accept — add a selection or answer text for pending questions first.',
        )
        setTimeout(() => setSubmitNotice(null), 3800)
        return
      }
      setApiSelections(prev =>
        mergeApiSelectionsForSubmit(reviewQuestions, prev, apiData.answers, nextQState, {
          questionsCatalog: apiQData?.questions || [],
        }),
      )
      setSubmitNotice(`Accepted ${changed} answer(s). Use Submit when ready to send to the server.`)
      setTimeout(() => setSubmitNotice(null), 3200)
      return
    }
    const patch = {}
    // Accept everything currently pending (not only AI-tagged signals).
    sections.forEach(sec =>
      sec.signals.forEach(sig =>
        sig.qs.forEach(q => {
          if (qState[q.id]?.status === 'pending') patch[q.id] = { status: 'accepted', isAccepted: true, isEdited: false, override: '', answerSource: 'ai' }
        }),
      ),
    )
    setQState(prev => { const next = { ...prev }; Object.entries(patch).forEach(([k, v]) => { next[k] = { ...next[k], ...v } }); return next })
  }, [
    unresolvedConflicts,
    apiFeatureOn,
    apiData?.answers,
    useApiLayout,
    qState,
    reviewQuestions,
    apiQuestionCardModelsById,
    apiSelections,
    apiQData?.questions,
    sections,
    isOpportunityReadOnly,
  ])

  const openSubmitModal = () => {
    if (isOpportunityReadOnly) return
    if (isSubmitting) return
    setSubmitConfirmValidation('')
    setSubmitConfirmMissing([])
    // Allow opening even when incomplete so the user can see exactly what's blocking Submit.
    if (!allQuestionsComplete) {
      const missing = Array.isArray(incompleteQuestions)
        ? incompleteQuestions.map(qid => ({ qid: String(qid), reason: 'Accept or override this question' }))
        : []
      setSubmitConfirmValidation(
        missing.length
          ? `Complete every answer before submitting (${missing.length} questions incomplete).`
          : 'Complete every answer before submitting.',
      )
      setSubmitConfirmMissing(missing)
    }
    setSubmitConfirmOpen(true)
  }

  const saveCurrentSectionToBackend = useCallback(async () => {
    const sectionQids = Array.from(
      new Set(
        (currentSectionQuestionsForCompletion || [])
          .map(questionCompletionKey)
          .filter(Boolean)
          .map(String),
      ),
    )
    if (sectionQids.length === 0) return 0
    const sectionReviewQuestions = sectionQids
      .map(qid => reviewQuestionById.get(String(qid)))
      .filter(Boolean)
    if (sectionReviewQuestions.length === 0) return 0

    // Keep merged selections computation available for future section-level save flows.
    mergeApiSelectionsForSubmit(
      sectionReviewQuestions,
      apiSelections,
      apiData?.answers || [],
      qState,
      { questionsCatalog: apiQData?.questions || [] },
    )
    return sectionReviewQuestions.length
  }, [currentSectionQuestionsForCompletion, reviewQuestionById, apiSelections, apiData?.answers, qState, apiQData?.questions])

  const saveAcceptedAnswersToSession = useCallback(() => {
    if (!oppId) return
    const existing = Array.isArray(readSessionSaves(oppId)) ? readSessionSaves(oppId) : []
    const byQid = new Map(
      existing
        .filter(entry => entry && entry.question_id != null)
        .map(entry => [String(entry.question_id), entry]),
    )
    const sectionQids = Array.from(
      new Set(
        (currentSectionQuestionsForCompletion || [])
          .map(questionCompletionKey)
          .filter(Boolean)
          .map(String),
      ),
    )
    const rawByQid = new Map((apiData?.answers || []).map(r => [String(r?.question_id ?? ''), r]))
    for (const qid of sectionQids) {
      const st = qState?.[qid]
      const status = String(st?.status ?? '').trim().toLowerCase()
      if (status !== 'accepted' && status !== 'overridden') {
        byQid.delete(qid)
        continue
      }
      const q = reviewQuestionById.get(qid)
      const sel = selectionRecordGet(apiSelections, qid)
      const selectedAnswer =
        Array.isArray(sel)
          ? sel
              .map(v => {
                const sid = String(v ?? '').trim()
                if (!sid) return ''
                const hit = q ? reviewAnswerOptions(q).find(o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid) : null
                return String(hit?.text ?? sid).trim()
              })
              .filter(Boolean)
              .join(', ')
          : (() => {
              const sid = String(sel ?? '').trim()
              if (!sid) return ''
              const hit = q ? reviewAnswerOptions(q).find(o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid) : null
              return String(hit?.text ?? sid).trim()
            })()
      const row = rawByQid.get(qid)
      const backendAnswer = row?.answer_value ?? row?.answer ?? ''
      const finalAnswer =
        String(st?.acceptedAnswerValue ?? '').trim() ||
        String(st?.editedAnswer ?? '').trim() ||
        String(st?.override ?? '').trim() ||
        String(selectedAnswer ?? '').trim() ||
        (Array.isArray(backendAnswer) ? backendAnswer.map(v => String(v ?? '').trim()).filter(Boolean).join(', ') : String(backendAnswer ?? '').trim())
      byQid.set(qid, {
        question_id: qid,
        status: 'accepted',
        selectedAnswer: finalAnswer,
      })
    }
    writeSessionSaves(oppId, Array.from(byQid.values()))
  }, [oppId, currentSectionQuestionsForCompletion, apiData?.answers, qState, reviewQuestionById, apiSelections])

  const handleSaveClick = useCallback(async () => {
    if (isOpportunityReadOnly || saveBusy) return
    setSubmitError(null)
    setSaveBusy(true)
    try {
      // Store accepted answers locally — no backend call here.
      // Submit is the only action that sends data to the server.
      saveAcceptedAnswersToSession()
      persistProgressSnapshot()
      showSaveToast('Saved.', 'success')
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e))
      setSubmitError(err)
      showSaveToast(err.message || 'Save failed.', 'error')
    } finally {
      setSaveBusy(false)
    }
  }, [
    isOpportunityReadOnly,
    saveBusy,
    saveAcceptedAnswersToSession,
    persistProgressSnapshot,
    showSaveToast,
  ])

  const handleSaveNextClick = useCallback(async () => {
    if (isOpportunityReadOnly || saveBusy) return
    setSubmitError(null)
    setSaveBusy(true)
    try {
      // Save locally first, then advance to the next review section.
      saveAcceptedAnswersToSession()
      persistProgressSnapshot()
      handleSaveNextSection()
      showSaveToast('Saved. Moved to next section.', 'success')
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e))
      setSubmitError(err)
      showSaveToast(err.message || 'Save failed.', 'error')
    } finally {
      setSaveBusy(false)
    }
  }, [
    isOpportunityReadOnly,
    saveBusy,
    saveAcceptedAnswersToSession,
    persistProgressSnapshot,
    handleSaveNextSection,
    showSaveToast,
  ])

  const handleBackToDashboard = useCallback(() => {
    persistProgressSnapshot()
    if (typeof onBack === 'function') onBack()
  }, [persistProgressSnapshot, onBack])

  const handleBackToConnectors = useCallback(() => {
    persistProgressSnapshot()
    if (typeof onBackToDataConnectors === 'function') onBackToDataConnectors()
  }, [persistProgressSnapshot, onBackToDataConnectors])

  const handleSubmitClick = useCallback(() => {
    if (isOpportunityReadOnly) return
    openSubmitModal()
  }, [openSubmitModal, isOpportunityReadOnly])

  const confirmSubmit = async () => {
    if (isOpportunityReadOnly) return
    if (isSubmitting) return
    const totalStart = performance.now()
    console.log('[Submit] Started at:', new Date().toISOString())
    console.log('[Submit Start]')
    setSubmitError(null)

    // In API mode, always route submit through POST /opportunities/{id}/answers.
    if (apiFeatureOn && apiOid) {
      const payloadStart = performance.now()
      const backendPendingQuestionIds = (apiData?.answers || [])
        .filter(a => String(a?.status ?? '').trim().toLowerCase() === 'pending')
        .map(a => String(a.question_id))
      const allQuestions = reviewQuestions
      const merged = mergeApiSelectionsForSubmit(allQuestions, apiSelections, apiData?.answers || [], qState, {
        questionsCatalog: apiQData?.questions || [],
      })
      setSubmitConfirmValidation('')
      /**
       * Per-card Accept sets `status: 'accepted'` and relies on `mergeApiSelectionsForSubmit` +
       * `backfillFromAcceptedState` for pick/multi ids — not necessarily `editedAnswer`.
       */
      const selectionsCheck = validateReviewSelectionsForSubmit(allQuestions, merged, qState, {
        opportunityId: apiOid,
        rawAnswerRows: apiData?.answers || [],
      })
      if (!selectionsCheck.ok) {
        setSubmitConfirmValidation(
          selectionsCheck.message || 'Complete every answer before submitting.',
        )
        const missing = selectionsCheck?.errorsByQid && typeof selectionsCheck.errorsByQid === 'object'
          ? Object.entries(selectionsCheck.errorsByQid).map(([qid, reason]) => ({
              qid: String(qid),
              reason: String(reason ?? '').trim() || 'Incomplete',
            }))
          : []
        setSubmitConfirmMissing(missing)
        return
      }
      const reqVal = validateRequiredReviewQuestions(allQuestions, merged, qState, {
        rawAnswerRows: apiData?.answers || [],
      })
      if (!reqVal.ok) {
        setSubmitConfirmValidation(reqVal.message)
        const missing = reqVal?.errorsByQid && typeof reqVal.errorsByQid === 'object'
          ? Object.entries(reqVal.errorsByQid).map(([qid, reason]) => ({
              qid: String(qid),
              reason: String(reason ?? '').trim() || 'Missing required answer',
            }))
          : []
        setSubmitConfirmMissing(missing)
        return
      }

      let updates = buildOpportunityReviewUpdates(allQuestions, merged, {
        qState,
        rawAnswerRows: apiData?.answers || [],
        opportunityId: apiOid,
        questionsCatalog: apiQData?.questions || [],
      })
      const rawByQid = new Map((apiData?.answers || []).map(r => [String(r.question_id ?? ''), r]))
      for (const q of allQuestions) {
        const qid = String(q?.question_id ?? '')
        if (!qid) continue
        const row = rawByQid.get(qid) || {}
        const mergedSel = selectionRecordGet(merged, qid)
        const selectedAnswer =
          Array.isArray(mergedSel)
            ? mergedSel
                .map(v => {
                  const sid = String(v ?? '').trim()
                  if (!sid) return ''
                  const hit = reviewAnswerOptions(q).find(
                    o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
                  )
                  return String(hit?.text ?? sid).trim()
                })
                .filter(Boolean)
                .join(', ')
            : (() => {
                const sid = String(mergedSel ?? '').trim()
                if (!sid) return ''
                const hit = reviewAnswerOptions(q).find(
                  o => String(o.id ?? '').trim() === sid || String(o.text ?? '').trim() === sid,
                )
                return String(hit?.text ?? sid).trim()
              })()
        const backendAnswer = row?.answer_value
        const finalSent =
          String(qState?.[qid]?.editedAnswer ?? '').trim() ||
          String(qState?.[qid]?.override ?? '').trim() ||
          selectedAnswer ||
          (Array.isArray(backendAnswer) ? backendAnswer.join(', ') : String(backendAnswer ?? '').trim()) ||
          null
      console.log('[Submit Payload Raw]', {
          qid,
          editedAnswer: qState?.[qid]?.editedAnswer ?? null,
          override: qState?.[qid]?.override ?? null,
          selected: selectedAnswer || null,
          backendAnswer,
          finalAnswer: finalSent,
        })
      }
      console.log('[Submit Payload Sanitized]', updates)
      if (import.meta.env.DEV) {
        console.info('[Submit debug] first-pass build', {
          pendingQuestionIds: backendPendingQuestionIds,
          builtUpdateQids: (updates || []).map(u => String(u?.q_id ?? '')).filter(Boolean),
          builtUpdatesCount: Array.isArray(updates) ? updates.length : 0,
        })
      }
      // Fallback: if strict pending-only question subset produced no updates,
      // retry with all non-active review questions.
      if ((!Array.isArray(updates) || updates.length === 0) && eligibleReviewQuestions.length > 0) {
        const mergedFallback = mergeApiSelectionsForSubmit(
          eligibleReviewQuestions,
          apiSelections,
          apiData?.answers || [],
          qState,
          { questionsCatalog: apiQData?.questions || [] },
        )
        updates = buildOpportunityReviewUpdates(eligibleReviewQuestions, mergedFallback, {
          qState,
          rawAnswerRows: apiData?.answers || [],
          opportunityId: apiOid,
          questionsCatalog: apiQData?.questions || [],
        })
        if (import.meta.env.DEV) {
          console.info('[Submit debug] fallback build', {
            nonActiveQuestionIds: eligibleReviewQuestions.map(q => String(q.question_id)),
            builtUpdateQids: (updates || []).map(u => String(u?.q_id ?? '')).filter(Boolean),
            builtUpdatesCount: Array.isArray(updates) ? updates.length : 0,
          })
        }
      }
      if (!Array.isArray(updates) || updates.length === 0) {
        setSubmitConfirmValidation('Nothing is left to submit.')
        return
      }
      const payloadEnd = performance.now()
      console.log('[Submit] Payload build time:', {
        ms: (payloadEnd - payloadStart).toFixed(2),
        totalQuestions: Array.isArray(updates) ? updates.length : 0,
      })

      const postConflictVal = validatePostConflictIds(updates, apiData?.answers || [])
      if (!postConflictVal.ok) {
        setSubmitConfirmValidation(postConflictVal.message)
        return
      }

      const answerIdVal = validatePostUpdatesAnswerIdsBelongToOpportunity(
        updates,
        apiQData?.questions || [],
        apiData?.answers || [],
      )
      if (!answerIdVal.ok) {
        setSubmitConfirmValidation(answerIdVal.message)
        return
      }

      // Final section has no "Save & next"; persist explicitly when user confirms submit.
      const acceptedMap = buildAcceptedMapFromState(qState)
      persistQaProgress(oppId, {
        activeSec,
        qState,
        apiSelections,
        updatedAt: Date.now(),
      })
      writeAcceptedAnswers(oppId, acceptedMap)

      setSubmitConfirmOpen(false)
      setSubmitBusy(true)
      try {
        const apiStart = performance.now()
        console.log('[POST Payload Manual]', updates.map(u => ({
          qid: u?.q_id ?? null,
          answer_id: u?.answer_id ?? null,
          override_value: u?.override_value ?? null,
          override_value_type: u?.override_value == null ? null : Array.isArray(u.override_value) ? 'array' : typeof u.override_value,
          answer_value: u?.answer_value ?? null,
          is_user_override: u?.is_user_override ?? null,
        })))
        const postJson = await postOpportunityUpdates(apiOid, { opp_id: apiOid, updates })
        const apiEnd = performance.now()
        console.log('[Submit] API call duration:', {
          ms: (apiEnd - apiStart).toFixed(2),
          seconds: ((apiEnd - apiStart) / 1000).toFixed(2),
        })
        console.log('[Submit] Response:', postJson)
        console.log('[Submit Success]')
        const ack = Array.isArray(postJson?.results) ? postJson.results.length : null
        setSubmitNotice(
          ack != null && postJson?.status === 'success'
            ? `Submitted · ${ack} saved`
            : 'Submitted',
        )
        setTimeout(() => setSubmitNotice(null), 2200)
        if (typeof refetchOpportunityQa === 'function') {
          await refetchOpportunityQa()
        }
        if (typeof onReviewSaved === 'function') {
          onReviewSaved()
        }
        /** Fresh GET /answers has UUIDs; old apiSelections may still hold studio ids / labels → merge memo would spam "Unmapped". */
        // Clear session-based section saves now that the backend has the data.
        clearSessionSaves(oppId)
        setApiSelections({})
        setShowSubmitSuccess(true)
        const totalEnd = performance.now()
        console.log('[Submit] Total end-to-end time:', {
          ms: (totalEnd - totalStart).toFixed(2),
          seconds: ((totalEnd - totalStart) / 1000).toFixed(2),
        })
      } catch (e) {
        const totalEnd = performance.now()
        console.log('[Submit] Total end-to-end time (failed):', {
          ms: (totalEnd - totalStart).toFixed(2),
          seconds: ((totalEnd - totalStart) / 1000).toFixed(2),
        })
        const err = e instanceof Error ? e : new Error(String(e))
        setSubmitError(err)
        setSubmitConfirmValidation(err.message || 'Submit failed.')
        setSubmitConfirmOpen(true)
      } finally {
        setSubmitBusy(false)
        console.log('[Submit End]')
      }
      return
    }

    setSubmitConfirmOpen(false)
    // Static catalog mode only: no POST.
    if (apiFeatureOn) {
      setSubmitNotice('Not sent to server — reload answers or check your connection, then try again.')
      setTimeout(() => setSubmitNotice(null), 4000)
    } else {
      setSubmitNotice('Submitted')
      setTimeout(() => setSubmitNotice(null), 2200)
    }
    const totalEnd = performance.now()
    console.log('[Submit] Total end-to-end time:', {
      ms: (totalEnd - totalStart).toFixed(2),
      seconds: ((totalEnd - totalStart) / 1000).toFixed(2),
    })
  }

  const renderApiQuestionCard = (a) => {
    try {
      const qModel =
        apiQuestionCardModelsById.get(a.question_id)
        || buildQuestionCardModelFromApiAnswer(a, questionTextById[a.question_id])
      const qidKey = String(a.question_id)
      const reviewRq = reviewQuestionById.get(qidKey) || null
      const catalogRq = catalogQuestionById.get(qidKey) || null
      const mergedOptionArrays = {}
      for (const key of [
        'answers',
        'answer_list',
        'answerList',
        'possible_answers',
        'possibleAnswers',
        'answer_options',
        'answerOptions',
        'options',
        'option_values',
        'optionValues',
        'answer_values',
        'answerValues',
      ]) {
        const catalogValue = catalogRq?.[key]
        const reviewValue = reviewRq?.[key]
        if (Array.isArray(catalogValue) && catalogValue.length > 0) {
          mergedOptionArrays[key] = catalogValue
        } else if (Array.isArray(reviewValue) && reviewValue.length > 0) {
          mergedOptionArrays[key] = reviewValue
        }
      }
      // Prefer merged catalog + review row (rich option arrays); fall back to full GET /questions / review list.
      const assistRqMerged =
        catalogRq || reviewRq
          ? {
              ...(reviewRq || {}),
              ...(catalogRq || {}),
              ...mergedOptionArrays,
              question_id: qidKey,
              answer_value: a?.answer_value ?? reviewRq?.answer_value ?? catalogRq?.answer_value,
              // Prefer GET /questions (catalog) answer_type so multi-select vs picklist matches the form definition, not only the answer row.
              answer_type: catalogRq?.answer_type ?? reviewRq?.answer_type ?? a?.answer_type,
              selected_answer_ids:
                a?.selected_answer_ids ??
                reviewRq?.selected_answer_ids ??
                catalogRq?.selected_answer_ids,
            }
          : null
      const assistRqFallback =
        apiQuestionsById.get(qidKey) ||
        reviewQuestions.find(r => String(r.question_id) === qidKey) ||
        null
      const assistRq = assistRqMerged || assistRqFallback
      return (
        <div key={`${oppId}-${a.question_id}`} id={apiAnswerElementId(a.question_id)}>
          <QuestionCard
            q={qModel}
            oppId={oppId}
            readOnly={isOpportunityReadOnly}
            qState={qState[String(a.question_id)] || DEFAULT_API_Q_STATE}
            onAccept={acceptQ}
            onUndo={undoQ}
            onSaveOverride={saveOverride}
            onEditOverride={editOverride}
            onSaveEdit={saveEdit}
            onSaveFeedback={saveFeedback}
            onResolveConflict={resolveConflict}
            onDraftAnswerChange={updateQDraft}
            onAssistSelectionDraft={handleAssistSelectionDraft}
            assistReviewQuestion={assistRq}
            conflictSelectionHint={
              Array.isArray(apiSelections[qidKey]) ? null : apiSelections[qidKey]
            }
            layout="assist"
          />
        </div>
      )
    } catch (e) {
      console.error('[QuestionCard Render Error]', {
        qid: a?.question_id ?? null,
        error: e instanceof Error ? e.message : String(e),
      })
      return (
        <div key={String(a?.question_id ?? Math.random())} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12, marginBottom: 8, background: 'var(--bg2)', color: '#b91c1c', fontSize: 12, fontWeight: 600 }}>
          Unable to load this question.
        </div>
      )
    }
  }

  const overallPct = totalQ ? Math.round((answeredQ / totalQ) * 100) : 0
  const activeSectionData = sections.find(s => s.id === activeSec)
  const sectionQs = activeSectionData
    ? activeSectionData.signals.filter(s => s.type === 'ai').flatMap(s => s.qs)
    : []
  const activeApiAnswers = useMemo(() => {
    if (!useApiLayout || !apiGrouped) return []
    if (activeSec === 'uncategorized') {
      return Array.isArray(apiGrouped.uncategorized) ? apiGrouped.uncategorized : []
    }
    const active = apiGrouped.sections.find(s => s.id === activeSec)
    if (!active) return []
    return (Array.isArray(active.subsections) ? active.subsections : []).flatMap(sub =>
      Array.isArray(sub.answers) ? sub.answers : [],
    )
  }, [useApiLayout, apiGrouped, activeSec])
  const isOpportunityAlreadySubmitted = useMemo(() => {
    if (!useApiLayout || !apiData?.answers?.length) return false
    return apiData.answers.every((a) => isQuestionServerLocked(a, qState[String(a.question_id)]))
  }, [useApiLayout, apiData?.answers, qState])
  const filteredActiveApiAnswers = useMemo(() => {
    if (!isOpportunityAlreadySubmitted) return activeApiAnswers
    return activeApiAnswers.filter((answerRow) => {
      const qid = String(answerRow?.question_id ?? '')
      const reviewQuestion = reviewQuestionById.get(qid) || null
      return shouldIncludeAnswerBySubmittedPayloadFilter({
        row: answerRow,
        filterId: answerFilter,
        qStateEntry: qState[qid],
        reviewQuestion,
      })
    })
  }, [activeApiAnswers, answerFilter, isOpportunityAlreadySubmitted, reviewQuestionById, qState])

  useEffect(() => {
    if (!isOpportunityAlreadySubmitted) setAnswerFilter('all')
  }, [isOpportunityAlreadySubmitted])

  useEffect(() => {
    if (!apiFeatureOn || !apiData?.answers?.length) return

    // Read both storage layers BEFORE entering setQState so we can guard against the
    // stale-prev race: this effect sometimes fires before React commits the [oppId]
    // localStorage-restore, leaving `prev` as the blank initial qState.  Reading storage
    // here lets us honour saved accepted answers even when prev.status is still empty.
    const _storedAccepted = readAcceptedAnswers(oppId)
    const _sessionSaved = readSessionSaves(oppId)
    const _sessionAcceptedQids = new Set(
      _sessionSaved
        .filter(e => e.status === 'accepted')
        .map(e => String(e.question_id ?? ''))
        .filter(Boolean),
    )
    const isStoredAccepted = (qid) =>
      Boolean(_storedAccepted[qid]) || _sessionAcceptedQids.has(String(qid))

    setQState(prev => {
      const next = { ...prev }
      let changed = false
      if (!apiReviewStateSeededRef.current) {
        for (const a of apiData.answers) {
          const qid = String(a.question_id)
          const payloadFeedbackVote = feedbackVoteFromAnswerRow(a)
          const payloadFeedbackText = feedbackTextFromAnswerRow(a)
          next[qid] = {
            ...DEFAULT_API_Q_STATE,
            serverLocked: isBackendAnswerActive(a),
            // Never map API `active` → local `accepted`; “active” is row lifecycle, not QA review completion.
            status: 'pending',
            feedback: payloadFeedbackVote,
            feedbackText: payloadFeedbackText,
          }
          changed = true
        }
        apiReviewStateSeededRef.current = true
        return changed ? next : prev
      }
      for (const a of apiData.answers) {
        const qid = String(a.question_id)
        const isLocked = isBackendAnswerActive(a)
        const payloadFeedbackVote = feedbackVoteFromAnswerRow(a)
        const payloadFeedbackText = feedbackTextFromAnswerRow(a)
        if (!next[qid]) {
          next[qid] = {
            ...DEFAULT_API_Q_STATE,
            serverLocked: isLocked,
            status: 'pending',
            feedback: payloadFeedbackVote,
            feedbackText: payloadFeedbackText,
          }
          changed = true
          continue
        }
        if (next[qid].serverLocked !== isLocked) {
          next[qid] = { ...next[qid], serverLocked: isLocked }
          changed = true
        }
        if ((next[qid].feedback == null || next[qid].feedback === '') && payloadFeedbackVote != null) {
          next[qid] = { ...next[qid], feedback: payloadFeedbackVote, feedbackText: payloadFeedbackText }
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [apiFeatureOn, apiData?.answers])

  useEffect(() => {
    const el = document.getElementById('qa-main-scroll')
    if (el) el.scrollTo({ top: 0, behavior: 'smooth' })
  }, [activeSec])

  useEffect(() => {
    if (!useApiLayout || !apiGrouped) return
    const allowed = new Set(apiGrouped.sections.map(s => s.id))
    if (apiGrouped.uncategorized.length) allowed.add('uncategorized')

    const countIn = (secId) => {
      if (secId === 'uncategorized') return apiGrouped.uncategorized.length
      const sec = apiGrouped.sections.find(s => s.id === secId)
      return sec ? sec.subsections.reduce((n, sub) => n + sub.answers.length, 0) : 0
    }

    if (activeSec && allowed.has(activeSec) && countIn(activeSec) > 0) return
    if (activeSec && allowed.has(activeSec) && countIn(activeSec) === 0) {
      const firstWith = apiGrouped.sections.find(s => s.subsections.some(sub => sub.answers.length > 0))
      if (firstWith) {
        setActiveSec(firstWith.id)
        return
      }
      if (apiGrouped.uncategorized.length) {
        setActiveSec('uncategorized')
        return
      }
      return
    }

    const firstWith = apiGrouped.sections.find(s => s.subsections.some(sub => sub.answers.length > 0))
    setActiveSec(firstWith?.id ?? (apiGrouped.uncategorized.length ? 'uncategorized' : apiGrouped.sections[0]?.id ?? null))
  }, [useApiLayout, apiGrouped, activeSec])

  const btnGhost = {
    padding: '8px 14px', borderRadius: 10, fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: 'var(--bg3)', color: 'var(--text1)', border: '1px solid var(--border)', fontFamily: 'var(--font)',
  }
  /** Sticky bar: same height / touch target for primary + secondary actions */
  const footBarBtnBase = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 40,
    padding: '0 18px',
    borderRadius: 10,
    fontSize: 13,
    fontWeight: 700,
    fontFamily: 'var(--font)',
    cursor: 'pointer',
    boxSizing: 'border-box',
    transition: 'transform .08s ease, box-shadow .12s ease, filter .12s ease',
  }

  const currentSessionNumber = activeSectionIdx >= 0 ? activeSectionIdx + 1 : 1
  const totalSessions = reviewSectionOrder.length
  const hasFourOrMoreSessions = totalSessions >= 4
  // Sessions 1–(N-1): show Save & Next; last session: show Submit.
  // For ≥4-session opportunities the 4th session (idx 3) is always the submit session
  // regardless of how many more sections follow (matching the original requirement).
  // For <4-session opportunities the last section is always the submit session.
  const isPreSubmitSession = totalSessions > 1 && activeSectionIdx >= 0 && (
    hasFourOrMoreSessions ? activeSectionIdx < 3 : !isLastReviewSection
  )
  const isFinalSubmitSession = activeSectionIdx >= 0 && (
    hasFourOrMoreSessions ? activeSectionIdx >= 3 : (totalSessions === 1 || isLastReviewSection)
  )

  const { acceptedAnswersCount, totalQuestionsCount } = useMemo(() => {
    let accepted = 0
    const total = allQuestionsForCompletion.length
    for (const q of allQuestionsForCompletion) {
      const qid = questionCompletionKey(q)
      if (!qid) continue
      if (isQuestionComplete(q, qState?.[qid])) accepted++
    }
    return { acceptedAnswersCount: accepted, totalQuestionsCount: total }
  }, [allQuestionsForCompletion, qState])

  const isSubmitEnabled = totalQuestionsCount > 0 && acceptedAnswersCount === totalQuestionsCount
  const showSaveNext = showSectionNav && isPreSubmitSession && !isOpportunityAlreadySubmitted
  const showSubmitButton = (showSectionNav && isFinalSubmitSession) || isOpportunityAlreadySubmitted
  const showSaveOnFinalSection = showSectionNav && isFinalSubmitSession && !isOpportunityAlreadySubmitted
  console.log('[Main Submit Render]', {
    isSubmitting,
    label: isSubmitting ? 'Submitting...' : 'Submit',
  })
  console.log('[Button Render]', {
    submitDisabled: !isSubmitEnabled,
    saveDisabled: false,
    currentSessionNumber,
    acceptedAnswersCount,
    totalQuestionsCount,
  })

  const qaContentMax = { maxWidth: 960, margin: 0, width: '100%', boxSizing: 'border-box' }

  return (
    <div style={{
      display: 'flex', flexDirection: 'row', alignItems: 'stretch',
      height: 'calc(100vh - 56px)', overflow: 'hidden', animation: 'fadeUp .22s ease',
      background: 'linear-gradient(165deg, #f4f1eb 0%, #f7f5f2 35%, #eef2f8 100%)',
    }}>

      {/* LEFT: full-height Qualification rail (matches reference layout) */}
      <aside style={{
        width: 280, flex: '0 0 280px',
        borderRight: '1px solid rgba(232,83,46,.14)',
        background: 'linear-gradient(180deg, rgba(255,255,255,.98) 0%, rgba(255,248,242,.88) 55%, rgba(241,245,252,.92) 100%)',
        display: 'flex', flexDirection: 'column', minHeight: 0, alignSelf: 'stretch',
      }}>
        <div style={{ flexShrink: 0, padding: '12px 16px 14px' }}>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.14em', color: SI_NAVY, marginBottom: 8 }}>QUALIFICATION</div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{overallPct}% Complete</span>
          </div>
          <div style={{ height: 8, background: 'var(--bg4)', borderRadius: 6, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${overallPct}%`, background: SI_ORANGE, borderRadius: 6, transition: 'width .35s ease' }} />
          </div>
          {conflictResolutionProgress.total > 0 ? (
            <div
              style={{
                marginTop: 10,
                fontSize: 11,
                fontWeight: 600,
                color: conflictResolutionProgress.resolved >= conflictResolutionProgress.total ? '#15803d' : 'var(--text2)',
                lineHeight: 1.4,
              }}
              role="status"
            >
              Conflicts: {conflictResolutionProgress.resolved}/{conflictResolutionProgress.total} resolved
              {conflictResolutionProgress.resolved < conflictResolutionProgress.total
                ? ` (${conflictResolutionProgress.total - conflictResolutionProgress.resolved} open)`
                : ''}
            </div>
          ) : null}
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(27,38,79,.08)' }}>
            <OpportunityExportMenu
              apiOppId={apiOid}
              opportunityName={resolvedOppName || 'Opportunity'}
              disabled={!apiFeatureOn || apiLoading}
              block
              menuAlignLeft
            />
          </div>
        </div>
        <div style={{
          flex: 1, minHeight: 0, overflowY: 'auto',
          padding: '4px 12px 24px', display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {useApiLayout && apiGrouped ? (
            <>
              {apiGrouped.sections.map(sec => {
                const count = sec.subsections.reduce((n, sub) => n + sub.answers.length, 0)
                const reviewed = sec.subsections.reduce(
                  (n, sub) =>
                    n +
                    sub.answers.filter(a => {
                      const st = qState[String(a.question_id)]?.status ?? 'pending'
                      return st === 'accepted' || st === 'overridden' || isQuestionServerLocked(a, qState[String(a.question_id)])
                    }).length,
                  0,
                )
                const conflictRows = sec.subsections.flatMap(sub =>
                  sub.answers.filter(a => apiAnswerNeedsConflictClarify(a)),
                )
                const conflictTotal = conflictRows.length
                const conflictResolved = conflictRows.filter(
                  a => qState[String(a.question_id)]?.conflictResolved,
                ).length
                const conflictOpen = conflictTotal - conflictResolved
                const isActive = sec.id === activeSec
                const RowIcon = SECTION_ROW_ICON[sec.id] || IconCompass
                return (
                  <button
                    key={sec.id}
                    type="button"
                    onClick={() => setActiveSec(sec.id)}
                    style={{
                      textAlign: 'left', cursor: 'pointer', borderRadius: 12, border: '1px solid', transition: 'all .15s ease',
                      borderColor: isActive ? 'var(--border)' : 'transparent',
                      background: isActive ? '#fff' : 'transparent',
                      boxShadow: isActive ? '0 2px 12px rgba(15,23,42,.06)' : 'none',
                      borderLeft: isActive ? `4px solid ${SI_NAVY}` : '4px solid transparent',
                      padding: '12px 12px 12px 10px',
                      fontFamily: 'var(--font)',
                    }}
                  >
                    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                      <div style={{
                        width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0, background: isActive ? 'rgba(27,38,79,.08)' : 'var(--bg3)', color: isActive ? SI_NAVY : 'var(--text2)',
                      }}>
                        <RowIcon size={20} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: isActive ? SI_NAVY : 'var(--text1)', lineHeight: 1.35 }}>{sec.title}</div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: isActive ? SI_ORANGE : 'var(--text3)', marginTop: 6 }}>
                          {reviewed}/{count} reviewed
                          {conflictTotal > 0
                            ? ` · ${[
                                conflictOpen > 0 ? `${conflictOpen} open` : null,
                                conflictResolved > 0 ? `${conflictResolved} resolved` : null,
                              ]
                                .filter(Boolean)
                                .join(' · ')}`
                            : ''}
                        </div>
                      </div>
                    </div>
                  </button>
                )
              })}
              {apiGrouped.uncategorized.length > 0 && (() => {
                const uc = apiGrouped.uncategorized
                const uRev = uc.filter(a => {
                  const st = qState[String(a.question_id)]?.status ?? 'pending'
                  return st === 'accepted' || st === 'overridden' || isQuestionServerLocked(a, qState[String(a.question_id)])
                }).length
                const ucConflictRows = uc.filter(a => apiAnswerNeedsConflictClarify(a))
                const ucConflictTotal = ucConflictRows.length
                const ucConflictResolved = ucConflictRows.filter(
                  a => qState[String(a.question_id)]?.conflictResolved,
                ).length
                const ucConflictOpen = ucConflictTotal - ucConflictResolved
                return (
                  <button
                    type="button"
                    onClick={() => setActiveSec('uncategorized')}
                    style={{
                      textAlign: 'left', cursor: 'pointer', borderRadius: 12, border: '1px solid', transition: 'all .15s ease',
                      borderColor: activeSec === 'uncategorized' ? 'var(--border)' : 'transparent',
                      background: activeSec === 'uncategorized' ? '#fff' : 'transparent',
                      boxShadow: activeSec === 'uncategorized' ? '0 2px 12px rgba(15,23,42,.06)' : 'none',
                      borderLeft: activeSec === 'uncategorized' ? `4px solid ${SI_NAVY}` : '4px solid transparent',
                      padding: '12px 12px 12px 10px',
                      fontFamily: 'var(--font)',
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 700, color: activeSec === 'uncategorized' ? SI_NAVY : 'var(--text1)', lineHeight: 1.35 }}>Other</div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: activeSec === 'uncategorized' ? SI_ORANGE : 'var(--text3)', marginTop: 6 }}>
                      {uRev}/{uc.length} reviewed
                      {ucConflictTotal > 0
                        ? ` · ${[
                            ucConflictOpen > 0 ? `${ucConflictOpen} open` : null,
                            ucConflictResolved > 0 ? `${ucConflictResolved} resolved` : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}`
                        : ''}
                    </div>
                  </button>
                )
              })()}
            </>
          ) : apiBundlePending ? (
            <div style={{ padding: '16px 12px', color: 'var(--text3)', fontSize: 13, fontWeight: 600, lineHeight: 1.45 }}>
              Loading answers…
            </div>
          ) : useStaticQualificationRail ? (
            sections.filter(s => !s.isSummary).map(sec => {
              const qs = sec.signals.filter(s => s.type === 'ai').flatMap(s => s.qs)
              const total = qs.length
              const reviewed = qs.filter(q => {
                const st = qState[q.id]?.status ?? 'pending'
                return st === 'accepted' || st === 'overridden' || isQuestionServerLocked(q, qState[q.id])
              }).length
              const isActive = sec.id === activeSec
              const RowIcon = SECTION_ROW_ICON[sec.id] || IconCompass
              return (
                <button
                  key={sec.id}
                  type="button"
                  onClick={() => setActiveSec(sec.id)}
                  style={{
                    textAlign: 'left', cursor: 'pointer', borderRadius: 12, border: '1px solid', transition: 'all .15s ease',
                    borderColor: isActive ? 'var(--border)' : 'transparent',
                    background: isActive ? '#fff' : 'transparent',
                    boxShadow: isActive ? '0 2px 12px rgba(15,23,42,.06)' : 'none',
                    borderLeft: isActive ? `4px solid ${SI_NAVY}` : '4px solid transparent',
                    padding: '12px 12px 12px 10px',
                    fontFamily: 'var(--font)',
                  }}
                >
                  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0, background: isActive ? 'rgba(27,38,79,.08)' : 'var(--bg3)', color: isActive ? SI_NAVY : 'var(--text2)',
                    }}>
                      <RowIcon size={20} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: isActive ? SI_NAVY : 'var(--text1)', lineHeight: 1.35 }}>{sec.title}</div>
                      <div style={{ fontSize: 11, fontWeight: 600, color: isActive ? SI_ORANGE : 'var(--text3)', marginTop: 6 }}>
                        {reviewed}/{total} reviewed
                      </div>
                    </div>
                  </div>
                </button>
              )
            })
          ) : null}
        </div>
      </aside>

      {/* RIGHT: header + scrollable questions */}
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0,
        background: 'linear-gradient(180deg, rgba(255,255,255,.4) 0%, rgba(248,250,252,.85) 100%)',
      }}>
        <div style={{
          flexShrink: 0,
          padding: '8px 16px 6px',
          borderBottom: '1px solid rgba(27,38,79,.08)',
          background: 'linear-gradient(135deg, rgba(232,83,46,.08) 0%, rgba(255,255,255,.96) 42%, rgba(99,102,241,.06) 100%)',
        }}>
          <div
            style={{
              ...qaContentMax,
              marginBottom: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 10,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minWidth: 0, flex: '1 1 200px' }}>
              <button type="button" onClick={handleBackToDashboard} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'var(--font)', color: 'var(--text3)', fontSize: 11, fontWeight: 500 }}>
                Knowledge Assist
              </button>
              <span style={{ color: 'var(--border)', userSelect: 'none' }}>&gt;</span>
              <button type="button" onClick={handleBackToConnectors} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'var(--font)', color: 'var(--text3)', fontSize: 11, fontWeight: 500 }}>
                Data Connectors
              </button>
              <span style={{ color: 'var(--border)', userSelect: 'none' }}>&gt;</span>
              <span style={{ color: 'var(--text2)', fontWeight: 600 }}>{resolvedOppName}</span>
            </div>
            {showOpportunityQuestionSearch ? (
              <div
                style={{
                  position: 'relative',
                  width: '100%',
                  maxWidth: 340,
                  flex: '1 1 240px',
                }}
              >
                <input
                  id="qa-question-search-header"
                  type="search"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Search questions…"
                  autoComplete="off"
                  aria-label="Search questions in this opportunity"
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    background: 'rgba(255,255,255,.92)',
                    border: '1px solid rgba(27,38,79,.12)',
                    borderRadius: 10,
                    padding: '6px 12px 6px 32px',
                    fontSize: 12,
                    color: 'var(--text0)',
                    fontFamily: 'var(--font)',
                    outline: 'none',
                    boxShadow: '0 1px 2px rgba(15,23,42,.04)',
                  }}
                />
                <span
                  aria-hidden
                  style={{
                    position: 'absolute',
                    left: 12,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    fontSize: 14,
                    opacity: 0.45,
                    pointerEvents: 'none',
                    lineHeight: 1,
                  }}
                >
                  ⌕
                </span>
                {showQuestionResults && filteredPredefinedQs.length === 0 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 'calc(100% + 6px)',
                      right: 0,
                      left: 0,
                      zIndex: 50,
                      padding: '10px 12px',
                      fontSize: 12,
                      color: 'var(--text3)',
                      borderRadius: 10,
                      border: '1px solid var(--border)',
                      background: 'var(--bg2)',
                      boxShadow: '0 8px 24px rgba(15,23,42,.1)',
                    }}
                  >
                    No matching questions.
                  </div>
                )}
                {showQuestionResults && filteredPredefinedQs.length > 0 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 'calc(100% + 6px)',
                      right: 0,
                      left: 0,
                      zIndex: 50,
                      maxHeight: 280,
                      overflowY: 'auto',
                      borderRadius: 10,
                      border: '1px solid var(--border)',
                      background: 'var(--bg2)',
                      boxShadow: '0 8px 24px rgba(15,23,42,.12)',
                    }}
                  >
                    {filteredPredefinedQs.slice(0, 12).map((item, idx) => (
                      <button
                        key={`${item.id}-hdr-${idx}`}
                        type="button"
                        onClick={() => navigateToSearchQuestion(item)}
                        style={{
                          display: 'block',
                          width: '100%',
                          textAlign: 'left',
                          padding: '10px 12px',
                          border: 'none',
                          borderBottom: idx < Math.min(11, filteredPredefinedQs.length - 1) ? '1px solid var(--border)' : 'none',
                          background: 'transparent',
                          cursor: 'pointer',
                          fontFamily: 'var(--font)',
                        }}
                      >
                        <div style={{ fontSize: 9, fontWeight: 700, color: SI_ORANGE, marginBottom: 2 }}>{item.sectionTitle}</div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)', lineHeight: 1.4 }}>{item.text}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>

          <div style={{ ...qaContentMax, marginBottom: 6 }}>
            <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.4px', color: SI_NAVY, lineHeight: 1.2 }}>{resolvedOppName}</div>
            <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 500, fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>{oppId}</div>
          </div>
          {useApiLayout && isOpportunityAlreadySubmitted && (apiData?.answers?.length ?? 0) > 0 ? (
            <div style={{ ...qaContentMax, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {[
                { id: 'all', label: 'All answers' },
                { id: 'ai', label: 'AI answers' },
                { id: 'human', label: 'Human answers' },
              ].map((opt) => {
                const active = answerFilter === opt.id
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setAnswerFilter(opt.id)}
                    style={{
                      padding: '5px 10px',
                      borderRadius: 999,
                      border: active ? `1px solid ${SI_ORANGE}` : '1px solid rgba(27,38,79,.16)',
                      background: active ? 'rgba(232,83,46,.10)' : 'rgba(255,255,255,.84)',
                      color: active ? SI_ORANGE : 'var(--text2)',
                      fontSize: 11,
                      fontWeight: active ? 700 : 600,
                      cursor: 'pointer',
                      fontFamily: 'var(--font)',
                    }}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
          ) : null}

          <div style={{ ...qaContentMax }}>
          {isOpportunityReadOnly ? (
            <div
              role="status"
              style={{
                marginBottom: 6,
                padding: '8px 12px',
                borderRadius: 6,
                background: '#FEF2F2',
                border: '1px solid #FECACA',
                color: '#991B1B',
                fontSize: 12,
                fontWeight: 700,
                lineHeight: 1.4,
              }}
            >
              This opportunity is locked. You can review answers, but editing and submission are disabled.
            </div>
          ) : null}
          {!submitReady && totalQ > 0 && (unresolvedConflicts > 0 || pendingFinalize > 0) ? (
            <div
              role="alert"
              style={{
                marginBottom: 6,
                padding: '8px 12px',
                borderRadius: 6,
                background: '#FEF2F2',
                border: '1px solid #FECACA',
                color: '#991B1B',
                fontSize: 12,
                fontWeight: 700,
                lineHeight: 1.4,
              }}
            >
              {unresolvedConflicts > 0 ? (
                <>
                  Submit is disabled until all conflicts are resolved ({unresolvedConflicts} remaining). Use each question’s
                  conflict options or <strong>Resolve conflicts</strong>.
                </>
              ) : (
                <>
                  Submit is disabled until every question is <strong>accepted</strong> or <strong>overridden</strong> (
                  {pendingFinalize} remaining).
                </>
              )}
            </div>
          ) : null}

          {submitNotice && (
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>{submitNotice}</div>
          )}
          {submitError && (
            <div role="alert" style={{ color: '#b91c1c', fontSize: 11, fontWeight: 600, marginBottom: 6 }}>
              Submit failed: {submitError.message}
            </div>
          )}

          {apiFeatureOn && apiError && !apiLoading && (
            <div
              role="alert"
              style={{
                marginBottom: 6,
                padding: '8px 10px',
                borderRadius: 8,
                border: '1px solid rgba(220,38,38,.35)',
                background: 'rgba(220,38,38,.06)',
                fontSize: 12,
                color: '#b91c1c',
                display: 'flex',
                flexWrap: 'wrap',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <span style={{ flex: 1, minWidth: 200 }}>Could not load answers: {apiError.message}</span>
              <button type="button" onClick={() => refetchOpportunityQa()} style={{ ...btnGhost, padding: '6px 12px' }}>Retry</button>
            </div>
          )}

          </div>
        </div>

        <div
          id="qa-main-scroll"
          style={{
            flex: 1,
            overflowY: 'auto',
            minHeight: 0,
            padding: '6px 16px 4px',
            background: 'linear-gradient(180deg, rgba(255,253,250,.5) 0%, rgba(241,245,252,.35) 100%)',
          }}
        >
          <div style={{ ...qaContentMax, paddingBottom: 12 }}>
            {apiFeatureOn && apiLoading && (
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: SI_NAVY, marginBottom: 8 }}>Loading questions and answers…</div>
                <OpportunityAnswersSkeleton count={4} />
              </div>
            )}
            {apiFeatureOn && !apiLoading && !apiError && apiData && (apiData.answers?.length ?? 0) === 0 && (
              <div style={{
                padding: 32,
                textAlign: 'center',
                borderRadius: 12,
                border: '1px dashed var(--border)',
                background: 'var(--bg2)',
                color: 'var(--text2)',
                fontSize: 14,
              }}>
                We're generating answers for this opportunity. They'll be ready shortly—please check back in around 15 minutes.
              </div>
            )}

            {useApiLayout && apiGrouped && (
              <>
                {showConflicts && conflictedQuestions.length > 0 && (
                  <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg2)', padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                      <div style={{ fontSize: 13, fontWeight: 800, color: SI_NAVY }}>Resolve Conflicts</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          onClick={() => setShowConflicts(false)}
                          style={{ ...footBarBtnBase, minHeight: 34, border: '1px solid var(--border)', background: 'var(--bg3)', color: 'var(--text2)' }}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={applyResolvedConflicts}
                          style={{ ...footBarBtnBase, minHeight: 34, border: 'none', background: SI_ORANGE, color: '#fff' }}
                        >
                          Apply Resolved Conflicts
                        </button>
                      </div>
                    </div>
                    {conflictedQuestions.map(q => (
                      <div key={q.question_id} style={{ borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 10 }}>
                        <h4 style={{ fontSize: 12, color: 'var(--text1)', marginBottom: 8 }}>{q.question_text || q.question_id}</h4>
                        {(q.conflicts || []).map((c, i) => (
                          <div key={`${q.question_id}-${i}`} style={{ marginBottom: 8, padding: 8, border: '1px solid rgba(27,38,79,.12)', borderRadius: 8 }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text1)' }}>
                              <input
                                type="radio"
                                name={`conf-${q.question_id}`}
                                checked={resolvedConflicts[q.question_id] === c.answer_value}
                                onChange={() => handleSelectConflict(q.question_id, c.answer_value)}
                              />
                              <span>{c.answer_value}</span>
                            </label>
                            {c.citations?.length > 0 && (
                              <div style={{ marginTop: 8, paddingLeft: 24 }}>
                                {c.citations.map((s, idx) => (
                                  <div key={`${q.question_id}-${i}-src-${idx}`} style={{ marginBottom: 6 }}>
                                    <b style={{ fontSize: 11 }}>{s.source_name || 'Source'}</b>
                                    <p style={{ fontSize: 11, color: 'var(--text2)', marginTop: 2 }}>{s.quote}</p>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
                {activeSec === 'uncategorized' ? (
                  filteredActiveApiAnswers.map(renderApiQuestionCard)
                ) : (
                  (() => {
                    if (activeApiAnswers.length === 0) return null
                    return filteredActiveApiAnswers.map(renderApiQuestionCard)
                  })()
                )}
                {isOpportunityAlreadySubmitted && activeApiAnswers.length > 0 && filteredActiveApiAnswers.length === 0 ? (
                  <div
                    style={{
                      border: '1px dashed var(--border)',
                      borderRadius: 10,
                      padding: '16px 14px',
                      background: 'var(--bg2)',
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--text3)',
                    }}
                  >
                    No questions match the selected answer filter.
                  </div>
                ) : null}
              </>
            )}

            {!useApiLayout && !apiBundlePending && activeSectionData && sectionQs.length > 0 && (
              <>
                {sectionQs.map(q => (
                  <div key={`${oppId}-${q.id}`}>
                    <QuestionCard
                      q={q}
                      oppId={oppId}
                      readOnly={isOpportunityReadOnly}
                      qState={qState[q.id] || { status: q.status, isAccepted: false, isEdited: false, override: '', editedAnswer: '', answerSource: 'ai', feedback: null, feedbackText: '', notes: '', conflictResolved: false, serverLocked: false }}
                      onAccept={acceptQ}
                      onUndo={undoQ}
                      onSaveOverride={saveOverride}
                      onEditOverride={editOverride}
                      onSaveEdit={saveEdit}
                      onSaveFeedback={saveFeedback}
                      onResolveConflict={resolveConflict}
                      onDraftAnswerChange={updateQDraft}
                      onAssistSelectionDraft={handleAssistSelectionDraft}
                      layout="assist"
                    />
                  </div>
                ))}
              </>
            )}
            {!useApiLayout && !(activeSectionData && sectionQs.length > 0) && !(apiFeatureOn && apiLoading) && !(apiFeatureOn && !apiLoading && !apiError && apiData && (apiData.answers?.length ?? 0) === 0) && (
              <div style={{ fontSize: 13, color: 'var(--text3)' }}>Select a section to review questions.</div>
            )}
          </div>
        </div>

        {showSectionNav && ((useApiLayout && (apiData?.answers?.length ?? 0) > 0) || totalQ > 0) && (
          <div
            role="contentinfo"
            aria-label="Qualification actions"
            style={{
              flexShrink: 0,
              padding: '10px 16px calc(10px + env(safe-area-inset-bottom, 0px))',
              borderTop: '1px solid rgba(27,38,79,.1)',
              background: 'linear-gradient(90deg, rgba(255,255,255,.98) 0%, rgba(248,245,238,.94) 100%)',
              boxShadow: '0 -4px 24px rgba(15,23,42,.06)',
            }}
          >
            <div
              className="qa-button-container"
              style={{
                ...qaContentMax,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                width: '100%',
              }}
            >
              <div className="qa-button-left-group" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
                {(useApiLayout && (apiData?.answers?.length ?? 0) > 0) || useStaticQualificationRail ? (
                  <button
                    type="button"
                    onClick={handleAcceptAll}
                    onMouseDown={() => setPressedFooterAction('accept-all')}
                    onMouseUp={() => setPressedFooterAction(null)}
                    onMouseLeave={() => setPressedFooterAction(null)}
                    disabled={submitBusy || isOpportunityAlreadySubmitted || isOpportunityReadOnly}
                    title="Accept every pending question using your current MCQ selections and sentence edits. Does not send to the server — use Submit for that."
                    style={{
                      ...footBarBtnBase,
                      border: '1px solid rgba(27,38,79,.22)',
                      background: 'var(--bg2)',
                      color: SI_NAVY,
                      boxShadow: pressedFooterAction === 'accept-all' ? 'inset 0 2px 8px rgba(15,23,42,.14)' : 'none',
                      opacity: submitBusy || isOpportunityAlreadySubmitted || isOpportunityReadOnly ? 0.7 : 1,
                      cursor: submitBusy || isOpportunityAlreadySubmitted || isOpportunityReadOnly ? 'not-allowed' : 'pointer',
                      transform: pressedFooterAction === 'accept-all' ? 'translateY(1px) scale(0.99)' : 'translateY(0) scale(1)',
                    }}
                  >
                    Accept all answers
                  </button>
                ) : null}
                {showSaveNext && (
                  <button
                    type="button"
                    onClick={handleSaveNextClick}
                    onMouseDown={() => setPressedFooterAction('save-next')}
                    onMouseUp={() => setPressedFooterAction(null)}
                    onMouseLeave={() => setPressedFooterAction(null)}
                    disabled={isOpportunityReadOnly || saveBusy}
                    style={{
                      ...footBarBtnBase,
                      border: 'none',
                      background: !isOpportunityReadOnly && !saveBusy ? SI_ORANGE : 'var(--bg3)',
                      color: !isOpportunityReadOnly && !saveBusy ? '#fff' : 'var(--text3)',
                      boxShadow: !isOpportunityReadOnly && !saveBusy
                        ? (pressedFooterAction === 'save-next' ? '0 1px 6px rgba(232,83,46,.22)' : '0 2px 10px rgba(232,83,46,.28)')
                        : 'none',
                      cursor: !isOpportunityReadOnly && !saveBusy ? 'pointer' : 'not-allowed',
                      opacity: !isOpportunityReadOnly && !saveBusy ? 1 : 0.7,
                      transform: pressedFooterAction === 'save-next' ? 'translateY(1px) scale(0.99)' : 'translateY(0) scale(1)',
                    }}
                  >
                    {saveBusy ? 'Saving...' : 'Save & Next'}
                  </button>
                )}
                {showSaveOnFinalSection && (
                  <button
                    type="button"
                    onClick={handleSaveClick}
                    onMouseDown={() => setPressedFooterAction('save')}
                    onMouseUp={() => setPressedFooterAction(null)}
                    onMouseLeave={() => setPressedFooterAction(null)}
                    disabled={isOpportunityReadOnly || saveBusy}
                    style={{
                      ...footBarBtnBase,
                      border: '1px solid rgba(27,38,79,.22)',
                      background: 'var(--bg2)',
                      color: SI_NAVY,
                      boxShadow: pressedFooterAction === 'save' ? 'inset 0 2px 8px rgba(15,23,42,.14)' : 'none',
                      opacity: !isOpportunityReadOnly && !saveBusy ? 1 : 0.7,
                      cursor: !isOpportunityReadOnly && !saveBusy ? 'pointer' : 'not-allowed',
                      transform: pressedFooterAction === 'save' ? 'translateY(1px) scale(0.99)' : 'translateY(0) scale(1)',
                    }}
                  >
                    {saveBusy ? 'Saving...' : 'Save'}
                  </button>
                )}
                {showSubmitButton && (
                  <button
                    type="button"
                    onClick={handleSubmitClick}
                    disabled={!isSubmitEnabled || isSubmitting || isOpportunityAlreadySubmitted || isOpportunityReadOnly}
                    title={
                      isOpportunityAlreadySubmitted
                        ? 'Responses are already submitted'
                        : !isSubmitEnabled
                        ? unresolvedConflicts > 0
                          ? 'Resolve all conflicts before submitting'
                          : 'Accept or override every question before submitting'
                        : undefined
                    }
                    style={{
                      ...footBarBtnBase,
                      border: 'none',
                      opacity: isSubmitEnabled && !isSubmitting && !isOpportunityAlreadySubmitted && !isOpportunityReadOnly ? 1 : 0.7,
                      cursor: isSubmitEnabled && !isSubmitting && !isOpportunityAlreadySubmitted && !isOpportunityReadOnly ? 'pointer' : 'not-allowed',
                      background: isSubmitEnabled && !isSubmitting && !isOpportunityAlreadySubmitted && !isOpportunityReadOnly ? SI_ORANGE : 'var(--bg3)',
                      color: isSubmitEnabled && !isSubmitting && !isOpportunityAlreadySubmitted && !isOpportunityReadOnly ? '#fff' : 'var(--text3)',
                      boxShadow: isSubmitEnabled && !isSubmitting && !isOpportunityAlreadySubmitted && !isOpportunityReadOnly ? '0 2px 10px rgba(232,83,46,.28)' : 'none',
                    }}
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit'}
                  </button>
                )}
              </div>
              <div
                className="qa-button-right-group"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  justifyContent: 'flex-end',
                }}
              >
                <button
                  type="button"
                  onClick={openBulkResolve}
                  disabled={bulkResolveConflictCount === 0 || isOpportunityReadOnly}
                  title={bulkResolveConflictCount === 0 || isOpportunityReadOnly ? 'No conflicts to resolve' : undefined}
                  style={{
                    ...footBarBtnBase,
                    opacity: bulkResolveConflictCount === 0 || isOpportunityReadOnly ? 0.5 : 1,
                    cursor: bulkResolveConflictCount === 0 || isOpportunityReadOnly ? 'not-allowed' : 'pointer',
                    border: `1px solid ${bulkResolveConflictCount > 0 && !isOpportunityReadOnly ? '#DC2626' : 'var(--border)'}`,
                    color: bulkResolveConflictCount > 0 && !isOpportunityReadOnly ? '#DC2626' : 'var(--text2)',
                    background: bulkResolveConflictCount > 0 && !isOpportunityReadOnly ? 'rgba(220,38,38,.06)' : 'var(--bg3)',
                  }}
                >
                  Resolve conflicts{bulkResolveConflictCount > 0 ? ` (${bulkResolveConflictCount})` : ''}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <ConflictResolutionModal
        open={Boolean(bulkResolveOpen && bulkConflictPresentation)}
        onClose={() => {
          setBulkResolveOpen(false)
          setBulkResolveIncludeResolved(false)
          setBulkConflictSessionTotal(0)
          setBulkConflictIndex(0)
        }}
        questionText={bulkConflictPresentation?.qModel.text ?? ''}
        conflicts={bulkConflictPresentation?.qModel.conflicts ?? []}
        stepLabel={bulkStepLabel}
        initialSelectedAnswer={
          bulkConflictPresentation &&
          qState[bulkConflictPresentation.qid]?.conflictResolved
            ? String(qState[bulkConflictPresentation.qid]?.editedAnswer ?? '').trim() || null
            : null
        }
        initialSelectedAnswerId={
          bulkConflictPresentation &&
          qState[bulkConflictPresentation.qid]?.conflictResolved
            ? (() => {
                const s = apiSelections[bulkConflictPresentation.qid]
                if (s == null || Array.isArray(s)) return null
                const t = String(s).trim()
                return t || null
              })()
            : null
        }
        omitPrimaryRecommendation={!bulkResolveIncludeResolved}
        onPrev={() => setBulkConflictIndex(i => Math.max(0, i - 1))}
        onNext={() => setBulkConflictIndex(i => Math.min(bulkConflictCandidates.length - 1, i + 1))}
        hasPrev={bulkConflictIndex > 0}
        hasNext={bulkConflictIndex < bulkConflictCandidates.length - 1}
        onConfirm={(chosen) => {
          const pres = bulkConflictPresentation
          if (!pres || chosen == null) return
          const text = typeof chosen === 'object' && chosen.answer != null
            ? String(chosen.answer).trim()
            : String(chosen).trim()
          if (!text) return

          const oldLen = bulkConflictCandidates.length
          const oldIdx = bulkConflictIndex

          resolveConflict(pres.qid, chosen)

          // Re-edit / browse resolved: list length stays the same — advance to next question or end session.
          if (bulkResolveIncludeResolved) {
            if (oldIdx < oldLen - 1) {
              setBulkConflictIndex(oldIdx + 1)
            } else {
              setBulkResolveOpen(false)
              setBulkResolveIncludeResolved(false)
              setBulkConflictSessionTotal(0)
              setBulkConflictIndex(0)
            }
            return
          }

          // Normal flow: current row drops from the list once conflictResolved is set.
          const newLen = Math.max(0, oldLen - 1)
          if (newLen === 0) {
            setBulkResolveOpen(false)
            setBulkResolveIncludeResolved(false)
            setBulkConflictSessionTotal(0)
            setBulkConflictIndex(0)
            return
          }
          setBulkConflictIndex(Math.min(oldIdx, newLen - 1))
        }}
      />

      {saveToast?.message ? (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: 'fixed',
            top: 72,
            right: 24,
            zIndex: 12000,
            padding: '12px 18px',
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 700,
            fontFamily: 'var(--font)',
            color: saveToast.type === 'error' ? '#991B1B' : '#14532D',
            background: saveToast.type === 'error' ? '#FEE2E2' : '#DCFCE7',
            border: saveToast.type === 'error' ? '1px solid #FCA5A5' : '1px solid #86EFAC',
            boxShadow: '0 8px 28px rgba(15,23,42,.18)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            animation: 'fadeUp .18s ease',
            pointerEvents: 'none',
          }}
        >
          <span aria-hidden style={{ fontSize: 16 }}>
            {saveToast.type === 'error' ? '✕' : '✓'}
          </span>
          {saveToast.message}
        </div>
      ) : null}

      {submitConfirmOpen && (
        <div
          onClick={() => setSubmitConfirmOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            background: 'rgba(15,23,42,.55)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            animation: 'fadeIn .15s ease',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: '92%',
              maxWidth: 420,
              background: 'var(--bg2)',
              borderRadius: 14,
              border: '1px solid var(--border)',
              boxShadow: '0 20px 50px rgba(0,0,0,.25), 0 0 0 1px rgba(255,255,255,.05)',
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 14, fontWeight: 800, color: SI_NAVY, marginBottom: 4 }}>Submit Confirmation</div>
              <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.5 }}>
                {canPostOpportunityReview
                  ? 'Submit all answers for every section in one request to the server?'
                  : 'Submit answers for the entire opportunity?'}
              </div>
              {submitConfirmValidation ? (
                <div role="alert" style={{ marginTop: 10, fontSize: 12, fontWeight: 600, color: '#b91c1c', lineHeight: 1.45 }}>
                  {submitConfirmValidation}
                </div>
              ) : null}
              {submitConfirmMissing.length > 0 ? (
                <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 10, background: 'rgba(185,28,28,.06)', border: '1px solid rgba(185,28,28,.16)' }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: '#991b1b', marginBottom: 6 }}>
                    Incomplete questions ({submitConfirmMissing.length})
                  </div>
                  <div style={{ maxHeight: 160, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {submitConfirmMissing.slice(0, 50).map((m) => (
                      <div key={m.qid} style={{ fontSize: 11, color: '#7f1d1d', lineHeight: 1.35 }}>
                        <span style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 800 }}>{m.qid}</span>
                        <span style={{ marginLeft: 8, fontWeight: 600, color: '#991b1b' }}>{m.reason}</span>
                      </div>
                    ))}
                    {submitConfirmMissing.length > 50 ? (
                      <div style={{ fontSize: 11, color: '#7f1d1d', fontWeight: 700 }}>
                        …and {submitConfirmMissing.length - 50} more
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
            <div style={{ padding: '12px 18px', display: 'flex', justifyContent: 'flex-end', gap: 8, background: 'var(--bg3)' }}>
              <button
                type="button"
                onClick={() => setSubmitConfirmOpen(false)}
                style={{ ...btnGhost, padding: '7px 14px' }}
              >
                No
              </button>
              <button
                type="button"
                onClick={confirmSubmit}
                  disabled={isSubmitting || !allQuestionsComplete}
                style={{
                  ...btnGhost,
                  padding: '7px 14px',
                  background: SI_NAVY,
                  color: '#fff',
                  border: '1px solid transparent',
                  opacity: isSubmitting || !allQuestionsComplete ? 0.7 : 1,
                  cursor: isSubmitting || !allQuestionsComplete ? 'not-allowed' : 'pointer',
                }}
              >
                {isSubmitting ? 'Submitting...' : 'Yes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSubmitSuccess && (
        <div
          onClick={() => setShowSubmitSuccess(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10000,
            background: 'rgba(15,23,42,.5)',
            backdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            animation: 'fadeIn .2s ease',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: '92%',
              maxWidth: 500,
              background: '#fff',
              borderRadius: 16,
              border: '1px solid rgba(15,23,42,.08)',
              boxShadow: '0 24px 60px rgba(15,23,42,.28)',
              padding: '22px 24px 20px',
              animation: 'fadeUp .2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div
                aria-hidden
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: '50%',
                  background: 'rgba(22,163,74,.14)',
                  color: '#15803d',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 20,
                  fontWeight: 800,
                }}
              >
                ✓
              </div>
              <div style={{ fontSize: 21, fontWeight: 800, color: SI_NAVY, letterSpacing: '-.02em' }}>
                Answers Submitted Successfully
              </div>
            </div>
            <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text2)', lineHeight: 1.6 }}>
              Your responses have been submitted successfully.
              <br />
              Thank you for completing the qualification review.
            </div>
            <div style={{ marginTop: 18, display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button
                type="button"
                onClick={() => setShowSubmitSuccess(false)}
                style={{ ...btnGhost, padding: '9px 14px' }}
              >
                Stay Here
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowSubmitSuccess(false)
                  handleBackToDashboard()
                }}
                style={{
                  ...btnGhost,
                  padding: '9px 16px',
                  background: SI_ORANGE,
                  color: '#fff',
                  border: '1px solid transparent',
                  boxShadow: '0 4px 14px rgba(232,83,46,.28)',
                }}
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}