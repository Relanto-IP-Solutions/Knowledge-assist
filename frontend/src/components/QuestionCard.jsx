import { useState, useMemo, useEffect, useLayoutEffect, useRef } from 'react'
import Badge from './Badge'
import { CitationBlock, SourcesGroupedPanel } from './ApiAnswerCard'
import { ConflictResolutionModal } from './ConflictResolutionModal'
import { SourceIcon } from './SourceIcons'
import {
  expandReviewPicklistOptionsForAssistUi,
  expandReviewMultiSelectOptionsForAssistUi,
  isReviewMultiSelectMode,
  isReviewPicklistRadiosMode,
  normalizeAnswerType,
  reviewAnswerOptions,
} from '../utils/opportunityReviewMeta'
import { parseSerializedListAnswerValue, serializeAssistMultiValue } from '../utils/opportunityAnswerRowToReviewQuestion'
import {
  areAnswersEquivalent,
  isAnswerOverrideAgainstAny,
  normalizedAnswerKey,
} from '../utils/overrideDetection'
import { getOptionDisplayLabel, getSelectedOption } from '../utils/getSelectedOption'
import { ReviewMultiCheckboxes, ReviewPicklistRadios } from './OpportunityReviewAnswerInputs'

/**
 * Only `picklist` / `multi-select` style questions use radios or checkboxes.
 * `integer`, `text`, `number`, etc. must stay free text — otherwise piclist catalog options
 * incorrectly turn them into multi-select and API values like `9995` never map to UUIDs (Accept stays disabled).
 */
function apiAnswerTypeUsesStructuredAssist(apiAnswerType) {
  const raw = String(apiAnswerType ?? '').toLowerCase().replace(/[\s-]+/g, '_')
  if (!raw) return false
  return (
    [
      'picklist',
      'single_select',
      'radio',
      'choice',
      'dropdown',
      'multi_select',
      'multiselect',
      'checkbox',
      'multi',
      'multiple',
      'list',
    ].includes(raw) || raw.includes('multi')
  )
}

/** GET /answers `answer_type` wins over catalog — never turn integer/number/text into picklist radios. */
function apiRowIsFreeFormAnswerType(apiAnswerType) {
  const raw = String(apiAnswerType ?? '').toLowerCase().replace(/[\s-]+/g, '_')
  if (!raw) return false
  return [
    'integer',
    'int',
    'bigint',
    'number',
    'decimal',
    'float',
    'double',
    'text',
    'textarea',
    'long_text',
    'free_text',
  ].includes(raw)
}

/** API often sends labels (`AES-256`) while options use UUID `id` — checkboxes match on id. */
function mapMultiSelectParsedValuesToOptionIds(questionId, parsed, opts) {
  if (!parsed?.length || !Array.isArray(opts)) return []
  const out = []
  const seen = new Set()
  for (const t of parsed) {
    const s = String(t).trim()
    if (!s) continue
    const byId = opts.find(o => String(o.id) === s)
    if (byId) {
      const id = String(byId.id)
      if (!seen.has(id)) {
        seen.add(id)
        out.push(id)
      }
      continue
    }
    const byText =
      opts.find(o => String(o.text).trim() === s) ||
      opts.find(o => String(o.text).trim().toLowerCase() === s.toLowerCase())
    if (byText) {
      const id = String(byText.id)
      if (!seen.has(id)) {
        seen.add(id)
        out.push(id)
      }
      continue
    }
    // Live API only: do not fallback to static/studio ids.
  }
  return out
}

/** Map draft multi values (ids, labels, or piclist labels) to canonical option ids for Accept / validation. */
function resolveMultiValuesToCanonicalIds(questionId, values, opts) {
  return mapMultiSelectParsedValuesToOptionIds(questionId, Array.isArray(values) ? values : [], opts)
}

/** Map draft pick value to canonical option id (id, option text, or piclist label). */
function resolvePickValueToCanonicalId(questionId, pickSel, opts) {
  const s = String(pickSel ?? '').trim()
  if (!s || !Array.isArray(opts)) return null
  const byLabel = getSelectedOption(opts, s)
  if (byLabel) return String(byLabel.id ?? '').trim() || null
  const byId = opts.find(o => String(o.id) === s)
  if (byId) return String(byId.id)
  const byText =
    opts.find(o => String(o.text).trim() === s) ||
    opts.find(o => String(o.text).trim().toLowerCase() === s.toLowerCase())
  if (byText) return String(byText.id)
  return null
}

function resolvePickSelectionPayload(selection, opts) {
  const selectedObj =
    selection != null && typeof selection === 'object' && !Array.isArray(selection) ? selection : null
  const rawId = String(selectedObj?.answer_id ?? selection ?? '').trim()
  const rawValue = String(selectedObj?.answer_value ?? '').trim()
  if (!rawId && !rawValue) return { answer_id: '', answer_value: '' }
  const match = Array.isArray(opts)
    ? (
      getSelectedOption(opts, rawValue) ||
      opts.find(o => {
        const oid = String(o?.id ?? '').trim()
        const ot = String(o?.text ?? '').trim()
        return (
          (rawId && (oid === rawId || ot === rawId)) ||
          (rawValue && (ot === rawValue || oid === rawValue))
        )
      })
    )
    : null
  const answer_id = String(match?.id ?? rawId).trim()
  let answer_value = String(getOptionDisplayLabel(match) || rawValue).trim()
  if (!answer_value && answer_id) answer_value = String(getOptionDisplayLabel(match) || answer_id).trim()
  if (answer_value && answer_id && answer_value === answer_id && match?.text) {
    answer_value = String(match.text).trim()
  }
  return { answer_id, answer_value }
}

function normalizeForMatch(value) {
  return String(value ?? '').trim().toLowerCase()
}

function resolvePersistedPickSelectedValue(persistedAcceptedValue, opts) {
  const needle = normalizeForMatch(persistedAcceptedValue)
  if (!needle || !Array.isArray(opts)) return ''
  const hit = opts.find((o) => {
    const id = normalizeForMatch(o?.id)
    const text = normalizeForMatch(o?.text)
    const label = normalizeForMatch(o?.label)
    const value = normalizeForMatch(o?.value)
    return needle === id || needle === text || needle === label || needle === value
  })
  return hit ? String(getOptionDisplayLabel(hit)).trim() : ''
}

function resolvePersistedMultiSelectedIds(persistedAcceptedValue, opts) {
  const raw = String(persistedAcceptedValue ?? '').trim()
  if (!raw || !Array.isArray(opts)) return []
  let parsed = []
  if (raw.startsWith('[')) {
    parsed = parseSerializedListAnswerValue(raw)
  } else {
    parsed = raw.split(',').map(v => String(v ?? '').trim()).filter(Boolean)
  }
  return mapMultiSelectParsedValuesToOptionIds('', parsed, opts)
}

function formatAnswerForDisplay(value, opts = []) {
  const mapValue = (raw) => {
    const needle = String(raw ?? '').trim()
    if (!needle) return ''
    const hit = opts.find(
      o => String(o.id ?? '').trim() === needle || String(o.text ?? '').trim() === needle,
    )
    return hit ? String(hit.text ?? needle).trim() : needle
  }
  if (Array.isArray(value)) return value.map(mapValue).filter(Boolean).join(', ')
  const raw = value == null ? '' : String(value).trim()
  if (!raw) return ''
  if (raw.startsWith('[')) {
    const parsed = parseSerializedListAnswerValue(raw)
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.map(mapValue).filter(Boolean).join(', ')
    }
  }
  return mapValue(raw)
}

function formatBackendAnswerDisplay(value) {
  if (value == null) return ''
  if (Array.isArray(value)) {
    return value.map(v => String(v ?? '').trim()).filter(Boolean).join(', ')
  }
  const raw = String(value).trim()
  if (!raw) return ''
  if (raw.startsWith('[')) {
    try {
      const parsed = parseSerializedListAnswerValue(raw)
      if (parsed.length > 0) {
        return parsed.map(v => String(v ?? '').trim()).filter(Boolean).join(', ')
      }
    } catch {
      // Keep raw fallback
    }
  }
  return raw
}

function aiComparableCandidates(question) {
  const out = []
  const pushIfAny = (value) => {
    const formatted = formatBackendAnswerDisplay(value)
    if (String(formatted ?? '').trim()) out.push(formatted)
  }
  /** Include both payload fields — mapper may set `answer_value` even when `answer` is empty or vice versa. */
  pushIfAny(question?.answer_value)
  pushIfAny(question?.answer)
  /**
   * Include answer_id as an AI-equivalent candidate.
   * Accept-All for unopened sections stores the raw UUID from pre-seeded apiSelections into
   * acceptedAnswerValue. Without this, the UUID-vs-label comparison fails and the card is
   * incorrectly labelled "ACCEPTED EDITED RESPONSE" instead of "ACCEPTED AI RESPONSE".
   */
  pushIfAny(question?.answer_id)
  const conflicts = Array.isArray(question?.conflicts) ? question.conflicts : []
  for (const conflict of conflicts) {
    pushIfAny(conflict?.answer ?? conflict?.answer_value ?? conflict?.value)
    pushIfAny(conflict?.answer_id)
  }
  return out
}

function getAcceptedHeading(question, qStateEntry) {
  const status = String(qStateEntry?.status ?? '').trim().toLowerCase()
  if (status !== 'accepted' && status !== 'overridden') return 'AI RECOMMENDED RESPONSE'

  const answerType = normalizeAnswerType(question)
  const options = reviewAnswerOptions(question)
  const edited = String(qStateEntry?.editedAnswer ?? '').trim()
  const override = String(qStateEntry?.override ?? '').trim()
  const backendCandidates = aiComparableCandidates(question)
  const currentValue = override || edited
  if (
    currentValue &&
    isAnswerOverrideAgainstAny(currentValue, backendCandidates, {
      answerType,
      options,
    })
  ) {
    return 'ACCEPTED USER RESPONSE'
  }
  if (backendCandidates.length > 0) return 'ACCEPTED AI RESPONSE'
  return 'ACCEPTED RESPONSE'
}

function arraysEqualAsStrings(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return false
  if (a.length !== b.length) return false
  return a.every((v, i) => String(v) === String(b[i]))
}

function normalizedKeyForEquality(value, opts = [], answerType = '') {
  return normalizedAnswerKey(value, { options: opts, answerType })
}

function valuesAreEquivalent(a, b, opts = [], answerType = '') {
  return areAnswersEquivalent(a, b, { options: opts, answerType })
}

const TABS_ASSIST = [
  { id: 'review', label: 'Review', icon: '✦' },
  { id: 'feedback', label: 'Feedback', icon: '💬' },
  { id: 'sources', label: 'Sources', icon: '◎' },
]
const TABS_DEFAULT_WITH_SOURCES = [
  { id: 'review', label: 'Review', icon: '✦' },
  { id: 'edit', label: 'Edit', icon: '✎' },
  { id: 'feedback', label: 'Feedback', icon: '💬' },
  { id: 'sources', label: 'Sources', icon: '◎' },
]
const TABS_DEFAULT_NO_SOURCES = [
  { id: 'review', label: 'Review', icon: '✦' },
  { id: 'edit', label: 'Edit', icon: '✎' },
  { id: 'feedback', label: 'Feedback', icon: '💬' },
]

const SI_NAVY = 'var(--si-navy, #1B264F)'
const SI_ORANGE = 'var(--si-orange, #E8532E)'

/** GET /answers `is_user_override` may be boolean or string on the wire. */
function normalizePayloadBooleanLike(value) {
  if (value === true || value === false) return value
  const t = String(value ?? '').trim().toLowerCase()
  if (t === 'true' || t === '1' || t === 'yes') return true
  if (t === 'false' || t === '0' || t === 'no') return false
  return null
}

const PLACEHOLDER_ANSWERS = new Set([
  'No extracted answer available for this question.',
  'No extracted answer available in payload for this question.',
])

/** Empty / known placeholder / backend “no AI” sentinel — show blank for editing, not the literal word. */
function isPlaceholderAnswerText(raw) {
  const t = String(raw ?? '').trim()
  if (!t) return true
  if (PLACEHOLDER_ANSWERS.has(t)) return true
  const cleaned = t.toLowerCase().replace(/\s+/g, ' ').replace(/[!?.,;:]+$/g, '')
  if (cleaned === 'user') return true
  if (cleaned === 'no answer given') return true
  if (cleaned === 'no answer generated') return true
  if (cleaned.includes('no extracted answer')) return true
  if (cleaned.includes('new answer generated')) return true
  if (cleaned === 'use edited') return true
  return false
}

function isInvalidBackendAnswerValue(value) {
  return isPlaceholderAnswerText(value)
}

function isValidAnswer(value) {
  if (value == null) return false
  if (Array.isArray(value)) {
    return value.some(v => !isPlaceholderAnswerText(v))
  }
  const s = String(value).trim()
  if (!s) return false
  if (s.startsWith('[')) {
    try {
      const parsed = parseSerializedListAnswerValue(s)
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed.some(v => !isPlaceholderAnswerText(v))
      }
    } catch {
      // Fall through to raw string validation.
    }
  }
  return !isPlaceholderAnswerText(s)
}

function getConflictFallbackAnswerFromQuestion(question) {
  const list = Array.isArray(question?.conflicts) ? question.conflicts : []
  for (const c of list) {
    const raw = c?.answer ?? c?.answer_value ?? null
    if (isValidAnswer(raw)) return formatBackendAnswerDisplay(raw)
  }
  return ''
}

function isAnswerNotProvided(q, qState, assistTextEditing, editText) {
  const s = qState?.status ?? 'pending'
  if (s === 'accepted' || s === 'overridden') return false
  if (String(qState?.editedAnswer ?? '').trim()) return false
  if (assistTextEditing && String(editText ?? '').trim()) return false
  return isPlaceholderAnswerText(q.answer)
}

const BRAND_CHIP = {
  zoom: {
    bg: 'rgba(219,234,254,.55)', border: 'rgba(59,130,246,.32)', color: SI_NAVY,
    logoBg: '#fff', short: 'Zoom',
  },
  gdrive: {
    bg: 'rgba(220,252,231,.55)', border: 'rgba(34,197,94,.3)', color: '#14532d',
    logoBg: '#fff', short: 'Google Drive',
  },
  gmail: {
    bg: 'rgba(254,215,200,.4)', border: 'rgba(232,83,46,.3)', color: '#C2410C',
    logoBg: '#fff', short: 'Gmail',
  },
  slack: {
    bg: 'rgba(252,231,243,.55)', border: 'rgba(190,24,93,.25)', color: '#831843',
    logoBg: '#fff', short: 'Slack',
  },
  ai: {
    bg: 'rgba(237,233,254,.65)', border: 'rgba(139,92,246,.28)', color: '#5B21B6',
    logoBg: '#fff', short: 'AI Intelligence',
  },
  none: {
    bg: 'var(--bg3)', border: 'var(--border)', color: 'var(--text2)',
    logoBg: 'var(--bg4)', short: 'Source',
  },
}

function AssistSourceChip({ s, minimal }) {
  const key = ['zoom', 'gdrive', 'gmail', 'slack', 'ai'].includes(s.type) ? s.type : (s.type === 'none' ? 'none' : 'ai')
  const tone = BRAND_CHIP[key] || BRAND_CHIP.none
  const useMinimal = Boolean(minimal || s.minimal)
  const parts = String(s.name || '').split('·').map(x => x.trim()).filter(Boolean)
  const rawSub = parts.length > 1 ? parts.slice(1).join(' · ') : (parts[0] && parts[0] !== tone.short ? parts[0] : '')
  const subtitle = rawSub.length > 56 ? `${rawSub.slice(0, 56)}…` : rawSub
  const iconType = s.type === 'none' ? 'ai' : s.type

  if (useMinimal) {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        padding: '6px 12px 6px 8px', borderRadius: 8,
        background: tone.bg, border: `1px solid ${tone.border}`, lineHeight: 1,
      }}>
        <span style={{
          width: 28, height: 28, borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0, background: tone.logoBg, border: '1px solid rgba(15,23,42,.06)',
        }}>
          <SourceIcon type={iconType} size={18} />
        </span>
        <span style={{
          fontSize: 10, fontWeight: 800, letterSpacing: '.1em', color: tone.color, textTransform: 'uppercase',
        }}>
          {tone.short}
        </span>
      </span>
    )
  }

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 10,
      padding: '8px 14px 8px 10px', borderRadius: 10,
      background: tone.bg, border: `1px solid ${tone.border}`, lineHeight: 1.2,
    }}>
      <span style={{
        width: 36, height: 36, borderRadius: 9, display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, background: tone.logoBg, border: '1px solid rgba(0,0,0,.06)', boxShadow: '0 1px 2px rgba(15,23,42,.06)',
      }}>
        <SourceIcon type={iconType} size={22} />
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', color: tone.color, textTransform: 'uppercase' }}>
          {tone.short}
        </span>
        {subtitle ? (
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', lineHeight: 1.35, wordBreak: 'break-word' }} title={rawSub}>
            {subtitle}
          </span>
        ) : null}
      </span>
    </span>
  )
}

export function QuestionCard({
  q,
  oppId,
  readOnly = false,
  qState,
  onAccept,
  onUndo,
  onSaveOverride,
  onEditOverride,
  onSaveEdit,
  onSaveFeedback,
  onResolveConflict,
  onDraftAnswerChange,
  /** Sync picklist / multiselect values to parent for API submit (no duplicate review list). */
  onAssistSelectionDraft,
  /** Merged GET /answers + /questions row — supplies UUID-backed `answers[]` so picklist radios match after Accept (editedAnswer is answer_id). */
  assistReviewQuestion = null,
  /** When re-opening conflict resolution, aligned API value (e.g. option id) helps match the prior choice. */
  conflictSelectionHint = null,
  layout = 'default',
}) {
  const assist = layout === 'assist'
  const citationList = Array.isArray(q.citations) ? q.citations : []
  const sortedCitationList = useMemo(() => {
    const toScore = (citation) => {
      const raw = citation?.relevance_score
      if (typeof raw === 'number' && Number.isFinite(raw)) return raw
      const parsed = Number(raw)
      return Number.isFinite(parsed) ? parsed : -Infinity
    }
    return [...citationList].sort((a, b) => toScore(b) - toScore(a))
  }, [citationList])
  const conflictList = Array.isArray(q.conflicts) ? q.conflicts : []
  const hasConflict = conflictList.length >= 2
  const conflictHasSourceData =
    citationList.length > 0 ||
    conflictList.some(c => {
      const citations = Array.isArray(c?.citations) ? c.citations : []
      if (citations.length > 0) return true
      return Boolean(
        String(c?.srcType ?? '').trim() ||
        String(c?.source_type ?? '').trim() ||
        String(c?.source_name ?? '').trim() ||
        String(c?.source_file ?? '').trim(),
      )
    })
  const shouldShowConflictNoSourcesInfo = hasConflict && !conflictHasSourceData
  const tabs = useMemo(() => {
    if (assist) return TABS_ASSIST
    return citationList.length > 0 ? TABS_DEFAULT_WITH_SOURCES : TABS_DEFAULT_NO_SOURCES
  }, [assist, citationList.length])

  const [activeTab, setActiveTab] = useState('review')
  const [editText, setEditText] = useState(formatAnswerForDisplay(qState.editedAnswer || q.answer))
  const [fbVote, setFbVote] = useState(qState.feedback)
  const [fbText, setFbText] = useState(qState.feedbackText || '')
  const [hover, setHover] = useState(false)
  const [fbSaved, setFbSaved] = useState(false)
  const [conflictOpen, setConflictOpen] = useState(false)
  /** Assist + plain text: inline edit instead of Edit tab */
  const [assistTextEditing, setAssistTextEditing] = useState(false)

  const st = qState.status
  const isAcceptedLike = st === 'accepted' || st === 'overridden'
  const prevStatusRef = useRef(st)
  const isSubmittedLocked =
    qState?.serverLocked === true || String(q?.status ?? '').trim().toLowerCase() === 'active'
  const isReadOnly = Boolean(readOnly || isSubmittedLocked)
  const acceptedCommittedValue = String(qState?.acceptedAnswerValue ?? '').trim()
  const payloadAnswerForDisplay = q.answer_value ?? q.answer
  const displayAnswer = (() => {
    if (st === 'accepted' || st === 'overridden') {
      if (acceptedCommittedValue) return acceptedCommittedValue
      if (st === 'overridden' && qState.override) return qState.override
      if (qState.editedAnswer) return qState.editedAnswer
      return payloadAnswerForDisplay
    }
    return qState.editedAnswer || (st === 'overridden' && qState.override ? qState.override : payloadAnswerForDisplay)
  })()
  const backendAnswerInvalid = isInvalidBackendAnswerValue(q?.answer_value ?? q?.answer)

  const assistAnswerStructured = useMemo(() => {
    const mergedAnswerType =
      assistReviewQuestion != null &&
      assistReviewQuestion.answer_type != null &&
      String(assistReviewQuestion.answer_type).trim() !== ''
        ? String(assistReviewQuestion.answer_type)
        : q.apiAnswerType
    if (!assist || !q.fromApi || !mergedAnswerType) return null
    if (apiRowIsFreeFormAnswerType(q.apiAnswerType)) return null
    if (!apiAnswerTypeUsesStructuredAssist(mergedAnswerType)) return null
    // Allow structured UI even when overridden (so conflict overrides still render as radios/checkboxes).
    const hasUnresolvedConflict = (q.conflicts?.length ?? 0) >= 2 && !qState.conflictResolved

    const raw = displayAnswer
    const d = raw == null ? '' : String(raw).trim()
    /** Treat placeholder copy as “no value” so we don’t fake a picklist selection or enable Accept. */
    const isPlaceholder = isPlaceholderAnswerText(d)

    const pseudoQ = {
      question_id: q.id,
      answer_type: mergedAnswerType,
      answer_value: isPlaceholder ? '' : raw,
    }
    /** Prefer merged review row (full option lists from GET /questions) over answer_value-only pseudo — avoids studio piclist ids vs API UUID mismatch after Accept. */
    const optionSourceQ =
      assistReviewQuestion != null && typeof assistReviewQuestion === 'object'
        ? { ...assistReviewQuestion, answer_value: isPlaceholder ? '' : raw }
        : pseudoQ
    let opts = reviewAnswerOptions(optionSourceQ)
    const normalizedType = normalizeAnswerType(optionSourceQ)
    if (normalizedType === 'picklist') {
      opts = expandReviewPicklistOptionsForAssistUi(q.id, opts)
    } else if (normalizedType === 'multi_select') {
      opts = expandReviewMultiSelectOptionsForAssistUi(q.id, opts)
    } else {
      // Sparse payloads often list only chosen value(s). Merge studio piclist when type is ambiguous.
      opts = expandReviewPicklistOptionsForAssistUi(q.id, opts)
    }
    /**
     * Defensive: if we failed to hydrate real options (e.g. assistReviewQuestion missing/empty),
     * but the API answer is a serialized list, split it into separate checkbox options.
     * This prevents the accepted view from collapsing into a single option like "['REST','GraphQL']".
     */
    if (opts.length <= 1) {
      const rawTrim = String(raw ?? '').trim()
      if (rawTrim.startsWith('[')) {
        const parsed = parseSerializedListAnswerValue(rawTrim).map(v => String(v ?? '').trim()).filter(Boolean)
        if (parsed.length >= 2) {
          opts = parsed.map(t => ({ id: t, text: t }))
        }
      }
    }
    // Extra defensive: sometimes the only option row itself contains the serialized list string.
    if (opts.length === 1) {
      const onlyText = String(opts[0]?.text ?? '').trim()
      if (onlyText.startsWith('[')) {
        const parsed = parseSerializedListAnswerValue(onlyText).map(v => String(v ?? '').trim()).filter(Boolean)
        if (parsed.length >= 2) {
          opts = parsed.map(t => ({ id: t, text: t }))
        }
      }
    }
    const n = opts.length
    if (n < 1) return null

    /** Only while unresolved: "conflict mode" forces picklist-style radios in meta. After resolve, use real multi vs pick so accepted multi-answers map to checkbox ids. */
    const reviewConflictId =
      (Boolean(assistReviewQuestion?.conflict?.conflict_id) || (q.conflicts?.length ?? 0) >= 2) &&
      !qState.conflictResolved
    const showMulti = isReviewMultiSelectMode(optionSourceQ, n, reviewConflictId)
    const showPick = isReviewPicklistRadiosMode(optionSourceQ, n, reviewConflictId)
    if (!showMulti && !showPick) return null

    let pickValue = ''
    let multiValue = []
    if (showMulti) {
      if (isPlaceholder) {
        multiValue = []
      } else {
        multiValue = parseSerializedListAnswerValue(raw)
        const t = String(raw).trim()
        if (multiValue.length === 0 && t && !t.startsWith('[')) {
          // Legacy drafts used `formatAnswerForDisplay` → comma-separated labels ("REST, GraphQL").
          // Split so each option maps to an id; a single token stays one value.
          const parts = t.split(/,\s*/).map(x => x.trim()).filter(Boolean)
          multiValue = parts.length > 1 ? parts : [t]
        }
        multiValue = multiValue.map(String)
        multiValue = mapMultiSelectParsedValuesToOptionIds(q.id, multiValue, opts)
      }
      // Conflict rows: keep full option list visible (read-only); Conflict modal handles resolution.
    } else {
      if (isPlaceholder) {
        pickValue = ''
      } else {
        const dFull = String(raw).trim()
        const lower = dFull.toLowerCase()
        const match =
          getSelectedOption(opts, dFull) ||
          opts.find(o => String(o.id) === dFull || String(o.text) === dFull) ||
          opts.find(o => String(o.text).trim().toLowerCase() === lower) ||
          opts.find(o => String(o.label ?? '').trim().toLowerCase() === lower) ||
          opts.find(o => String(o.value ?? '').trim().toLowerCase() === lower)
        // Never auto-pick the only catalog option when the API sent no matching value — that looked "selected" with answer_value null.
        pickValue = match ? String(getOptionDisplayLabel(match)) : ''
        if (!pickValue && dFull && !dFull.startsWith('[') && !isPlaceholderAnswerText(dFull)) {
          pickValue = dFull
        }
      }
    }

    // Conflict resolution must start neutral: no preselected radio/checkbox values.
    if (hasUnresolvedConflict) {
      pickValue = ''
      multiValue = []
    }
    return { showMulti, showPick, opts, pickValue, multiValue, hasUnresolvedConflict }
    // Use conflict count, not q.conflicts reference — parent rebuilds `q` each render so [] is a new identity.
  }, [
    assist,
    q.fromApi,
    q.apiAnswerType,
    q.id,
    q.conflicts?.length,
    qState.conflictResolved,
    st,
    displayAnswer,
    q.answer_value,
    q.answer,
    assistReviewQuestion,
    assistReviewQuestion?.answer_type,
    q.apiAnswerType,
  ])

  const [assistPickSel, setAssistPickSel] = useState('')
  const [assistMultiSel, setAssistMultiSel] = useState([])
  const handleAssistPickSelection = selected => {
    if (isAcceptedLike || isSubmittedLocked) return
    const opts = assistAnswerStructured?.opts || []
    const normalized = resolvePickSelectionPayload(selected, opts)
    setAssistPickSel(normalized.answer_value || normalized.answer_id)
    const label = normalized.answer_value || formatAnswerForDisplay(normalized.answer_id, opts)
    onDraftAnswerChange?.(q.id, label)
  }
  const handleAssistMultiSelection = value => {
    if (isAcceptedLike || isSubmittedLocked) return
    const next = Array.isArray(value) ? [...value] : []
    setAssistMultiSel(next)
    const opts = assistAnswerStructured?.opts || []
    const ids = resolveMultiValuesToCanonicalIds(q.id, next, opts)
    // Bracket JSON so `parseSerializedListAnswerValue` round-trips; comma-separated labels do not.
    const wire = ids.length ? serializeAssistMultiValue(ids) : ''
    onDraftAnswerChange?.(q.id, wire)
  }

  useEffect(() => {
    if (!assistAnswerStructured) return
    if (assistAnswerStructured.showMulti) {
      setAssistMultiSel([...(assistAnswerStructured.multiValue || [])])
      setAssistPickSel('')
      return
    }
    setAssistPickSel(assistAnswerStructured.pickValue || '')
    setAssistMultiSel([])
  }, [
    oppId,
    q.id,
    assistAnswerStructured?.showMulti,
    assistAnswerStructured?.pickValue,
    assistAnswerStructured?.multiValue,
  ])

  useLayoutEffect(() => {
    if (!assistAnswerStructured) {
      prevStatusRef.current = st
      return
    }
    const prev = prevStatusRef.current
    if (prev !== st) {
      // Pre-paint sync on status flips (accepted <-> pending) to prevent one-frame
      // stale selection flashes while local draft state catches up.
      if (assistAnswerStructured.showMulti) {
        setAssistMultiSel([...(assistAnswerStructured.multiValue || [])])
        setAssistPickSel('')
      } else {
        setAssistPickSel(assistAnswerStructured.pickValue || '')
        setAssistMultiSel([])
      }
    }
    prevStatusRef.current = st
  }, [
    st,
    assistAnswerStructured?.showMulti,
    assistAnswerStructured?.pickValue,
    assistAnswerStructured?.multiValue,
  ])

  const assistControlsDisabled =
    !assistAnswerStructured ||
    isReadOnly ||
    assistAnswerStructured?.hasUnresolvedConflict === true ||
    isAcceptedLike ||
    (!qState?.conflictResolved && st !== 'pending')
  const displayAnswerResolved = useMemo(() => {
    const raw = displayAnswer == null ? '' : String(displayAnswer).trim()
    if (!raw) return raw
    const opts = assistAnswerStructured?.opts || []
    const normalized = formatBackendAnswerDisplay(raw)
    return formatAnswerForDisplay(normalized, opts)
  }, [displayAnswer, assistAnswerStructured?.opts])

  const hasAssistStructured = Boolean(assistAnswerStructured)
  const assistStructuredMulti = assistAnswerStructured?.showMulti === true

  useEffect(() => {
    if (!assist || !onAssistSelectionDraft || !assistAnswerStructured || assistControlsDisabled) return
    if (st === 'accepted' || st === 'overridden') return
    if (assistAnswerStructured.showMulti) {
      onAssistSelectionDraft(q.id, { mode: 'multi', value: [...assistMultiSel] })
    } else {
      onAssistSelectionDraft(q.id, { mode: 'pick', value: assistPickSel })
    }
  }, [
    assist,
    q.id,
    assistPickSel,
    assistMultiSel,
    hasAssistStructured,
    assistStructuredMulti,
    assistControlsDisabled,
    st,
    onAssistSelectionDraft,
  ])

  useEffect(() => {
    if (!assist || !onDraftAnswerChange || !assistAnswerStructured || isReadOnly) return
    // Conflict cards already sync via explicit selection handlers and modal confirm;
    // auto draft-sync here can bounce value identity (id/label) and cause UI flicker.
    if ((q.conflicts?.length ?? 0) >= 2) return
    // Fix: do NOT sync draft when already accepted/overridden — this would overwrite
    // answerSource back to 'user' (via updateQDraft) even for pure AI accepted answers.
    if (st === 'accepted' || st === 'overridden') return
    if (assistAnswerStructured.showMulti) {
      const baseline = resolveMultiValuesToCanonicalIds(
        q.id,
        assistAnswerStructured.multiValue || [],
        assistAnswerStructured.opts || [],
      )
      const current = resolveMultiValuesToCanonicalIds(
        q.id,
        assistMultiSel,
        assistAnswerStructured.opts || [],
      )
      if (arraysEqualAsStrings(current, baseline)) return
      const wire = current.length ? serializeAssistMultiValue(current) : ''
      console.log('[MCQ Draft Sync]', {
        qid: q.id,
        selectedValue: wire,
      })
      onDraftAnswerChange(q.id, wire)
    } else {
      const baseline = String(assistAnswerStructured.pickValue ?? '').trim()
      const current = String(assistPickSel ?? '').trim()
      if (current === baseline) return
      const label = formatAnswerForDisplay(assistPickSel, assistAnswerStructured.opts || [])
      console.log('[MCQ Draft Sync]', {
        qid: q.id,
        selectedValue: label,
      })
      onDraftAnswerChange(q.id, label)
    }
  }, [
    assist,
    q.id,
    st,
    assistAnswerStructured,
    assistMultiSel,
    assistPickSel,
    onDraftAnswerChange,
    isReadOnly,
    q.conflicts?.length,
  ])

  useEffect(() => {
    if (!assist || !assistTextEditing || !onDraftAnswerChange || isReadOnly) return
    onDraftAnswerChange(q.id, editText)
  }, [assist, assistTextEditing, editText, q.id, onDraftAnswerChange, isReadOnly])

  const assistStructuredSelectionMissing = useMemo(() => {
    if (!assistAnswerStructured) return false
    const opts = assistAnswerStructured.opts || []
    if (assistAnswerStructured.showMulti) {
      const canonical = resolveMultiValuesToCanonicalIds(q.id, assistMultiSel, opts)
      return canonical.length === 0
    }
    const p = String(assistPickSel ?? '').trim()
    if (p === '') return true
    if (isPlaceholderAnswerText(p)) return true
    return false
  }, [assistAnswerStructured, q.id, assistMultiSel, assistPickSel])

  /** Plain text (no picklist UI): allow Accept only when user typed or saved text, or API returned real text. */
  const plainAssistCanAccept = useMemo(() => {
    if (assistAnswerStructured) return true
    if (String(qState.editedAnswer ?? '').trim()) return true
    if (assistTextEditing && String(editText ?? '').trim()) return true
    const a = String(q.answer ?? '').trim()
    return Boolean(a && !isPlaceholderAnswerText(a))
  }, [assistAnswerStructured, qState.editedAnswer, assistTextEditing, editText, q.answer, q.id])

  const assistUserHasDraftSelection = useMemo(() => {
    if (!assistAnswerStructured) return false
    if (assistAnswerStructured.showMulti) {
      const canonical = resolveMultiValuesToCanonicalIds(q.id, assistMultiSel, assistAnswerStructured.opts || [])
      return canonical.length > 0
    }
    return String(assistPickSel ?? '').trim() !== ''
  }, [assistAnswerStructured, assistMultiSel, assistPickSel])

  const assistUserHasAnyResponse =
    assistUserHasDraftSelection ||
    Boolean(String(qState?.editedAnswer ?? '').trim()) ||
    Boolean(String(qState?.override ?? '').trim())
  const selectedDerivedValue = assistAnswerStructured
    ? assistAnswerStructured.showMulti
      ? formatAnswerForDisplay(assistMultiSel, assistAnswerStructured.opts || [])
      : formatAnswerForDisplay(assistPickSel, assistAnswerStructured.opts || [])
    : ''
  const backendDisplayValue = formatBackendAnswerDisplay(q?.answer_value ?? q?.answer)
  const conflictFallback = getConflictFallbackAnswerFromQuestion(q)
  const effectiveDisplayAnswer =
    (qState?.conflictResolved ? (String(qState?.editedAnswer ?? '').trim() || String(qState?.override ?? '').trim()) : '') ||
    String(qState?.editedAnswer ?? '').trim() ||
    String(qState?.override ?? '').trim() ||
    String(selectedDerivedValue ?? '').trim() ||
    String(displayAnswerResolved ?? '').trim() ||
    String(backendDisplayValue ?? '').trim() ||
    String(conflictFallback ?? '').trim()
  const hasValidDisplayAnswer = isValidAnswer(effectiveDisplayAnswer)
  const backendAnswerText = String(q?.answer_value ?? q?.answer ?? '').trim()
  const backendAnswerId = String(
    q?.answer_id ??
    assistReviewQuestion?.final_answer_id ??
    assistReviewQuestion?.answer_id ??
    (Array.isArray(conflictSelectionHint) ? '' : conflictSelectionHint ?? ''),
  ).trim()
  const editedAnswerText = String(qState?.editedAnswer ?? '').trim()
  const overrideText = String(qState?.override ?? '').trim()
  const hasBackendAI = Boolean(
    (backendAnswerText && !isPlaceholderAnswerText(backendAnswerText)) ||
    citationList.length > 0,
  )
  const optsForCompare = assistAnswerStructured?.opts || []
  const comparisonAnswerType = assistAnswerStructured?.showMulti
    ? 'multi_select'
    : assistAnswerStructured?.showPick
      ? 'picklist'
      : normalizeAnswerType(assistReviewQuestion || q || { answer_type: q?.apiAnswerType || '' })
  // Value-equality keys. Equal key ⇒ same logical answer (order-independent
  // for multi-select, label↔id aware, trim/case/whitespace normalized).
  const normalizedBackendComparable = normalizedKeyForEquality(
    backendAnswerText,
    optsForCompare,
    comparisonAnswerType,
  )
  const normalizedEditDraftComparable = normalizedKeyForEquality(
    editText,
    optsForCompare,
    comparisonAnswerType,
  )
  const overrideMatchesBackend =
    Boolean(overrideText) &&
    valuesAreEquivalent(overrideText, backendAnswerText, optsForCompare, comparisonAnswerType)
  // Structured selection equality is order-independent (multi) and label↔id aware (pick).
  const userChangedStructuredSelection = Boolean(
    assistAnswerStructured &&
      (
        (assistAnswerStructured.showMulti &&
          !valuesAreEquivalent(
            assistMultiSel,
            assistAnswerStructured.multiValue || [],
            assistAnswerStructured.opts || [],
            'multi_select',
          )) ||
        (!assistAnswerStructured.showMulti &&
          !valuesAreEquivalent(
            assistPickSel,
            assistAnswerStructured.pickValue,
            assistAnswerStructured.opts || [],
            'picklist',
          ))
      ),
  )
  const userTypedDraft = Boolean(
    assistTextEditing &&
    normalizedEditDraftComparable !== '' &&
    normalizedEditDraftComparable !== normalizedBackendComparable,
  )
  const userChangedSelectionDraft = st === 'pending' && userChangedStructuredSelection
  // NOTE: `override` / `answerSource` stored on qState are NOT treated as a
  // permanent "user edited" flag. The truth is derived from the current value
  // vs the backend AI value — so re-selecting the AI option reverts the UI
  // back to "AI RECOMMENDED RESPONSE" automatically.
  const manualCurrentValue = overrideText || editedAnswerText
  const manualComparedToAiIsOverride = manualCurrentValue !== '' &&
    isAnswerOverrideAgainstAny(
      manualCurrentValue,
      aiComparableCandidates(q),
      {
        answerType: comparisonAnswerType,
        options: optsForCompare,
      },
    )
  const userHasEdited =
    manualComparedToAiIsOverride ||
    userTypedDraft ||
    userChangedSelectionDraft ||
    (!hasBackendAI && editedAnswerText !== '')
  const userHasEditedForLabel = manualComparedToAiIsOverride || (!hasBackendAI && editedAnswerText !== '')
  // Derive `answerSource` purely from value equality — ignore any stale flag
  // previously written to qState.answerSource.
  const answerSource = userHasEditedForLabel ? 'user' : 'ai'
  // Fix: do NOT use answerSource here — updateQDraft can corrupt it to 'user' even for pure AI
  // answers (draft-sync effect fires after accept and calls onDraftAnswerChange with the same text).
  // The only reliable signal is whether the stored text actually differs from the backend answer.
  const payloadIsUserOverride = normalizePayloadBooleanLike(q?.is_user_override)
  const acceptedComparableValue =
    acceptedCommittedValue ||
    overrideText ||
    editedAnswerText ||
    String(displayAnswerResolved ?? '').trim()
  const acceptedValueLooksUserEdited =
    Boolean(acceptedComparableValue) &&
    isAnswerOverrideAgainstAny(
      acceptedComparableValue,
      aiComparableCandidates(q),
      {
        answerType: comparisonAnswerType,
        options: optsForCompare,
      },
    )
  const acceptedHasLocalUserEvidence =
    st === 'overridden' ||
    Boolean(overrideText) ||
    acceptedValueLooksUserEdited
  // Accepted labels must depend on current committed value vs AI baseline only.
  const acceptedByUser =
    isAcceptedLike &&
    (
      // Value-comparison evidence (override text, edited value differs from AI)
      acceptedHasLocalUserEvidence ||
      // No backend AI at all but user provided a value
      (!hasBackendAI && Boolean(acceptedComparableValue))
    )
  // AI accepted iff committed value is equivalent to AI baseline.
  const acceptedByAi = isAcceptedLike && !acceptedByUser
  const pendingHasUserEdits =
    st === 'pending' &&
    (
      userChangedStructuredSelection ||
      userTypedDraft ||
      manualComparedToAiIsOverride ||
      (!hasBackendAI && assistUserHasAnyResponse)
    )
  const reviewHeading =
    isAcceptedLike
      ? acceptedByAi
        ? 'ACCEPTED AI RESPONSE'
        : acceptedByUser
          ? 'ACCEPTED USER RESPONSE'
          : 'ACCEPTED RESPONSE'
      : pendingHasUserEdits
        ? 'EDITED RESPONSE'
        : hasBackendAI
          ? 'AI RECOMMENDED RESPONSE'
          : 'NO EXTRACTED ANSWER'
  const acceptBtnLabel =
    userHasEdited ? 'Accept Answer' : hasBackendAI ? 'Accept AI Answer' : 'Accept Answer'
  const isAccepted = st === 'accepted'
  const hasUnresolvedConflict = (q.conflicts?.length ?? 0) >= 2 && !qState.conflictResolved
  /** No placeholder-only “answer” may be accepted unless the user edited / selected / typed something. */
  const canAcceptThisQuestion = hasValidDisplayAnswer && (hasBackendAI || userHasEdited)
  const shouldDisableSingleAccept =
    isAccepted ||
    isSubmittedLocked ||
    hasUnresolvedConflict ||
    !canAcceptThisQuestion

  if (hasConflict) {
    console.log('[Conflict Render]', {
      qid: q.id,
      conflictsCount: conflictList.length,
      citationsCount: citationList.length,
      preselectedValue: '',
    })
  }

  console.log('[Single Accept Button]', {
    qid: q.id,
    backendAnswer: q?.answer_value ?? q?.answer ?? null,
    conflictFallback,
    effectiveDisplayAnswer,
    hasValidDisplayAnswer,
    isAccepted,
    isLocked: isSubmittedLocked,
    hasUnresolvedConflict,
    shouldDisable: shouldDisableSingleAccept,
  })
  console.log('[Answer Source Detection]', {
    qid: q.id,
    backendAnswer: backendAnswerText,
    editedAnswer: editedAnswerText,
    overrideAnswer: overrideText,
    answerSource,
    userHasEdited,
    status: qState?.status,
  })
  console.log('[Accept Source]', {
    qid: q.id,
    backendAnswer: backendAnswerText,
    editedAnswer: editedAnswerText,
    answerSource,
    status: qState?.status,
  })
  console.log('[Answer Label Debug]', {
    qid: q.id,
    backendAnswer: backendAnswerText,
    editedAnswer: editedAnswerText,
    overrideAnswer: overrideText,
    userHasEdited: userHasEditedForLabel,
    answerSource,
    status: qState?.status,
  })

  const handleAssistAccept = () => {
    console.log('[Accept Handler Entered]', {
      qid: q.id,
      hasHandler: !!onAccept,
      hasValidDisplayAnswer,
      userHasEdited,
      isSubmittedLocked,
      status: st,
    })
    if (!canAcceptThisQuestion) {
      console.log('[Accept Handler Exit]', { qid: q.id, reason: 'no-extraction-without-user-input' })
      return
    }
    if ((q.conflicts?.length ?? 0) >= 2 && !qState.conflictResolved) {
      console.log('[Accept Handler Exit]', { qid: q.id, reason: 'conflict-unresolved-no-user-edit' })
      return
    }
    if (!assistAnswerStructured) {
      const typed = assistTextEditing && String(editText ?? '').trim()
      const saved = String(qState.editedAnswer ?? '').trim()
      const fromDisplay = String(displayAnswer ?? '').trim()
      const fromApiOk = Boolean(fromDisplay && !isPlaceholderAnswerText(fromDisplay))
      if (typed) {
        onAccept?.(q.id, { manualValue: typed })
        onSaveEdit?.(q.id, typed)
        setAssistTextEditing(false)
        return
      }
      if (saved) {
        onAccept?.(q.id, { manualValue: saved })
        return
      }
      /** Accept AI / API plain text without editing — parent needs `assistSelection` to sync `editedAnswer` + submit selections. */
      if (fromApiOk) {
        onAccept?.(q.id, { assistSelection: { mode: 'pick', pick: fromDisplay } })
        return
      }
      console.log('[Accept Handler Exit]', { qid: q.id, reason: 'no-valid-value-plain' })
      return
    }
    if (assistAnswerStructured.showMulti) {
      const ids = resolveMultiValuesToCanonicalIds(q.id, assistMultiSel, assistAnswerStructured.opts || [])
      const selectedLabel = formatAnswerForDisplay(assistMultiSel, assistAnswerStructured.opts || [])
      const shouldTreatMultiAcceptAsUserEdit =
        userChangedStructuredSelection || !hasBackendAI
      if (ids.length === 0) {
        if (isValidAnswer(selectedLabel)) {
          onAccept?.(q.id, { manualValue: selectedLabel })
          return
        }
        const fromApiOk = Boolean(String(displayAnswer ?? '').trim() && !isPlaceholderAnswerText(String(displayAnswer ?? '').trim()))
        if (fromApiOk) {
          const fallbackLabel = formatAnswerForDisplay(displayAnswer, assistAnswerStructured.opts || [])
          onAccept?.(q.id, { manualValue: fallbackLabel || String(displayAnswer).trim() })
        }
        console.log('[Accept Handler Exit]', { qid: q.id, reason: 'multi-no-canonical-id' })
        return
      }
      console.log('[Structured Accept Debug]', {
        opportunityId: oppId,
        qid: q.id,
        mode: 'multi',
        backendAnswer: backendAnswerText,
        selectedLabel,
        ids,
        shouldTreatAsUserEdit: shouldTreatMultiAcceptAsUserEdit,
      })
      onAccept?.(q.id, {
        assistSelection: { mode: 'multi', multi: ids },
        ...(shouldTreatMultiAcceptAsUserEdit ? { manualValue: selectedLabel } : {}),
      })
      return
    }
    const pickId = resolvePickValueToCanonicalId(q.id, assistPickSel, assistAnswerStructured.opts || [])
    const selectedLabel = formatAnswerForDisplay(assistPickSel, assistAnswerStructured.opts || [])
    const shouldTreatPickAcceptAsUserEdit =
      userChangedStructuredSelection || !hasBackendAI
    if (!pickId) {
      if (isValidAnswer(selectedLabel)) {
        onAccept?.(q.id, { manualValue: selectedLabel })
        return
      }
      const fromApiOk = Boolean(String(displayAnswer ?? '').trim() && !isPlaceholderAnswerText(String(displayAnswer ?? '').trim()))
      if (fromApiOk) {
        const fallbackLabel = formatAnswerForDisplay(displayAnswer, assistAnswerStructured.opts || [])
        onAccept?.(q.id, { manualValue: fallbackLabel || String(displayAnswer).trim() })
      }
      console.log('[Accept Handler Exit]', { qid: q.id, reason: 'pick-no-canonical-id' })
      return
    }
    console.log('[Structured Accept Debug]', {
      opportunityId: oppId,
      qid: q.id,
      mode: 'pick',
      backendAnswer: backendAnswerText,
      selectedLabel,
      pickId,
      shouldTreatAsUserEdit: shouldTreatPickAcceptAsUserEdit,
    })
    onAccept?.(q.id, {
      assistSelection: { mode: 'pick', pick: { answer_id: pickId, answer_value: selectedLabel } },
      ...(shouldTreatPickAcceptAsUserEdit ? { manualValue: selectedLabel } : {}),
    })
  }

  const visualStatus = st === 'overridden' && overrideMatchesBackend ? 'accepted' : st
  const statusLabel = visualStatus === 'accepted' ? '✓ Accepted' : visualStatus === 'overridden' ? '✎ Overridden' : ''
  const answerNotProvided = isAnswerNotProvided(q, qState, assistTextEditing, editText)
  const borderAccent = visualStatus === 'accepted' ? '#56D364' : visualStatus === 'overridden' ? '#E3B341' : answerNotProvided ? '#FCA5A5' : 'var(--border2)'
  // Accepted display must come from committed answer fields only; do not depend
  // on transient draft-derived flags to avoid accept/undo visual bouncing.
  const selectedValue = String(
    qState?.acceptedAnswerValue ||
    editedAnswerText ||
    overrideText ||
    backendAnswerText ||
    (assistAnswerStructured ? backendAnswerId : ''),
  ).trim()
  const acceptedSelectedValue = selectedValue
  const persistedAcceptedValue = String(
    st === 'accepted' || st === 'overridden'
      ? acceptedSelectedValue
      : (q?.answer_value ?? q?.answer ?? (assistAnswerStructured ? backendAnswerId : '')),
  ).trim()
  const payloadHighlightOptionIds = useMemo(() => {
    if (!assistAnswerStructured) return []
    if (hasUnresolvedConflict) return []
    const rawPayload = String(q?.answer_value ?? backendAnswerId ?? '').trim()
    if (!rawPayload || isPlaceholderAnswerText(rawPayload)) return []
    const opts = assistAnswerStructured?.opts || []
    if (assistAnswerStructured.showMulti) {
      const parsed = rawPayload.startsWith('[')
        ? parseSerializedListAnswerValue(rawPayload)
        : rawPayload.split(/,\s*/).map(v => String(v ?? '').trim()).filter(Boolean)
      return resolveMultiValuesToCanonicalIds(q.id, parsed, opts)
    }
    const pickId = resolvePickValueToCanonicalId(q.id, rawPayload, opts)
    return pickId ? [pickId] : []
  }, [assistAnswerStructured, q?.answer_value, backendAnswerId, q.id])
  const readonlyPickValue = resolvePersistedPickSelectedValue(
    persistedAcceptedValue,
    assistAnswerStructured?.opts || [],
  )
  // Text-based fallback: if strict label match misses, keep direct display value mapping.
  const textBasedPickValue = !readonlyPickValue && assistAnswerStructured?.opts?.length
    ? (assistAnswerStructured.opts.find(o =>
        String(getOptionDisplayLabel(o)).trim().toLowerCase() ===
        persistedAcceptedValue.toLowerCase()
      ) ? persistedAcceptedValue : '')
    : ''
  const payloadPickValue = (!readonlyPickValue && !textBasedPickValue && payloadHighlightOptionIds.length > 0)
    ? String(
      getOptionDisplayLabel(
        (assistAnswerStructured?.opts || []).find(
          o => String(o?.id ?? '').trim() === String(payloadHighlightOptionIds[0]).trim(),
        ),
      ) || '',
    ).trim()
    : ''
  const readonlyMultiValue = resolvePersistedMultiSelectedIds(
    persistedAcceptedValue,
    assistAnswerStructured?.opts || [],
  )
  /**
   * Flicker fix: after Undo (accepted -> pending), local UI state can briefly
   * retain the previously accepted selection for one render. Use baseline-first
   * unless the user has an actual pending draft delta.
   */
  const pendingPickValue =
    assistAnswerStructured?.showMulti
      ? ''
      : hasUnresolvedConflict
        ? ''
      : (
          assistAnswerStructured?.pickValue ||
          readonlyPickValue ||
          textBasedPickValue ||
          assistPickSel ||
          ''
        )
  const pendingMultiValue =
    assistAnswerStructured?.showMulti
      ? (
          hasUnresolvedConflict
            ? []
            : (
                assistAnswerStructured?.multiValue?.length
                  ? assistAnswerStructured.multiValue
                  : (readonlyMultiValue.length ? readonlyMultiValue : assistMultiSel)
              )
        )
      : []
  const pickRadioValue = st === 'accepted' || st === 'overridden'
    ? readonlyPickValue || textBasedPickValue || payloadPickValue || assistPickSel
    : pendingPickValue
  const multiCheckboxValue = st === 'accepted' || st === 'overridden'
    ? (readonlyMultiValue.length ? readonlyMultiValue : assistMultiSel)
    : pendingMultiValue

  console.log('[Accepted Render Debug]', {
    qid: q.id,
    backendAnswer: backendAnswerText,
    editedAnswer: editedAnswerText,
    overrideAnswer: overrideText,
    selectedValue,
    userHasEdited: userHasEditedForLabel,
    status: st,
  })
  console.log('[Payload Selected Render]', {
    opportunityId: oppId,
    qid: q.id,
    status: st,
    backendAnswer: backendAnswerText,
    assistPickSel,
    assistMultiSel,
    derivedPickValue: assistAnswerStructured?.pickValue || '',
    renderedPickValue: pickRadioValue,
    renderedMultiValue: multiCheckboxValue,
  })

  if ((assistAnswerStructured?.showPick || assistAnswerStructured?.showMulti) && (st === 'accepted' || st === 'overridden')) {
    console.log('[MCQ Selected Render]', {
      qid: q.id,
      answerSource,
      persistedAcceptedValue,
      selectedPick: pickRadioValue,
      readonlyPickValue,
      textBasedPickValue,
      selectedMulti: multiCheckboxValue,
      options: (assistAnswerStructured?.opts || []).map(o => o?.label || o?.text || o?.value || o?.id),
    })
  }

  const hasFeedbackValue = qState.feedback != null && qState.feedback !== ''
  const hasFeedback = hasFeedbackValue
  const feedbackLocked = isReadOnly || hasFeedbackValue
  const hasEdit = (qState.editedAnswer || '').trim().length > 0
  const acceptedResponseHeading = getAcceptedHeading(q, qState)

  useEffect(() => {
    if (activeTab === 'sources' && citationList.length === 0 && !assist) setActiveTab('review')
  }, [activeTab, citationList.length, assist, q.id])

  useEffect(() => {
    if (assist && activeTab === 'edit') setActiveTab('review')
  }, [assist, activeTab])

  useEffect(() => {
    setAssistTextEditing(false)
    setAssistPickSel('')
    setAssistMultiSel([])
  }, [oppId, q.id])

  useEffect(() => {
    if (hasAssistStructured) setAssistTextEditing(false)
  }, [hasAssistStructured])

  useEffect(() => {
    if (!assistTextEditing) {
      setEditText(formatAnswerForDisplay(displayAnswer != null ? String(displayAnswer) : String(q.answer ?? '')))
    }
  }, [assistTextEditing, displayAnswer, q.answer, oppId, q.id])

  useEffect(() => {
    setFbVote(qState.feedback ?? null)
    setFbText(qState.feedbackText || '')
  }, [oppId, q.id, qState.feedback, qState.feedbackText])

  useEffect(() => {
    console.log('[Opportunity Answer Source Debug]', {
      opportunityId: oppId,
      qid: q.id,
      backendAnswer: backendAnswerText,
      editedAnswer: editedAnswerText,
      override: overrideText,
      answerSource,
      status: qState?.status,
    })
  }, [oppId, q.id, backendAnswerText, editedAnswerText, overrideText, answerSource, qState?.status])

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={assist ? {
        borderRadius: 12,
        border: answerNotProvided ? '1px solid rgba(248,113,113,0.72)' : '1px solid rgba(232,83,46,.22)',
        background: answerNotProvided ? '#fff' : 'linear-gradient(180deg, #ffffff 0%, #fffbf7 55%, #f8fafc 100%)',
        marginBottom: 8,
        overflow: 'hidden',
        boxShadow: answerNotProvided
          ? '0 1px 3px rgba(248,113,113,.12), 0 4px 20px rgba(248,113,113,.08)'
          : '0 2px 10px rgba(27,38,79,.06), 0 1px 0 rgba(232,83,46,.1) inset',
      } : {
        borderRadius: 14,
        border: `1px solid ${answerNotProvided ? 'rgba(248,113,113,0.65)' : hover ? 'rgba(27,38,79,.22)' : 'var(--border)'}`,
        background: 'var(--bg2)', marginBottom: 8, overflow: 'hidden',
        transition: 'border-color .2s ease, box-shadow .2s ease',
        boxShadow: hover ? '0 4px 20px rgba(27,38,79,.08)' : '0 1px 3px rgba(15,23,42,.04)',
      }}
    >

      {/* ── Header ─────────────────────────────────────────── */}
      {assist ? (
        <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid rgba(232,83,46,.1)', background: 'linear-gradient(90deg, rgba(232,83,46,.04) 0%, rgba(255,255,255,.6) 40%, rgba(99,102,241,.04) 100%)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 300px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
                <div style={{ fontSize: 14, fontWeight: 800, color: SI_NAVY, lineHeight: 1.35, letterSpacing: '-0.15px', flex: '1 1 200px', minWidth: 0 }}>{q.text}</div>
                {q.fromApi && (q.srcs || []).filter(s => s.type !== 'none').length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flexShrink: 0 }}>
                    {(q.srcs || []).filter(s => s.type !== 'none').map(s => (
                      <button
                        key={s.type}
                        type="button"
                        onClick={() => citationList.length > 0 && setActiveTab('sources')}
                        disabled={citationList.length === 0}
                        title={citationList.length > 0 ? 'View source excerpts' : undefined}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          padding: 0,
                          border: 'none',
                          background: 'transparent',
                          cursor: citationList.length > 0 ? 'pointer' : 'default',
                          fontFamily: 'var(--font)',
                        }}
                      >
                        <AssistSourceChip s={s} minimal />
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {q.fromApi && (
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', marginTop: 4, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.04em' }}>
                  {q.id}
                </div>
              )}
              {answerNotProvided && (
                <div
                  role="status"
                  style={{
                    marginTop: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    color: '#B91C1C',
                    lineHeight: 1.4,
                  }}
                >
                  Answer not given — no extracted or entered response for this question yet.
                </div>
              )}
              {isSubmittedLocked && (
                <div
                  role="status"
                  style={{
                    marginTop: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    color: 'var(--text2)',
                    lineHeight: 1.4,
                  }}
                >
                  This answer has already been submitted and cannot be edited.
                </div>
              )}
            </div>
            {!q.fromApi && (q.srcs?.length ?? 0) > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flexShrink: 0 }}>
                {q.srcs.filter(s => s.type !== 'none').map(s => (
                  <AssistSourceChip key={`${s.type}-${s.name}`} s={s} minimal={Boolean(s.minimal)} />
                ))}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            {isSubmittedLocked && (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700,
                padding: '5px 11px', borderRadius: 20, background: 'rgba(27,38,79,.08)', border: '1px solid rgba(27,38,79,.22)',
                color: SI_NAVY, lineHeight: 1,
              }}>
                Already Submitted
              </span>
            )}
            {q.conflicts?.length >= 2 && (
              <button
                type="button"
                onClick={() => {
                  if (isAcceptedLike || isReadOnly) return
                  setConflictOpen(true)
                }}
                disabled={isAcceptedLike || isReadOnly}
                aria-label={`Open conflict options (${q?.conflicts?.length ?? 0})`}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700,
                  padding: '5px 11px', borderRadius: 20, background: '#FCE8E6', border: '1px solid rgba(185,28,28,.22)',
                  color: '#9F1239', lineHeight: 1,
                  cursor: isAcceptedLike || isReadOnly ? 'not-allowed' : 'pointer',
                  opacity: isAcceptedLike || isReadOnly ? 0.6 : 1,
                  fontFamily: 'var(--font)',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#BE123C" strokeWidth="2.5" strokeLinecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                Conflict · {q?.conflicts?.length ?? 0} options
              </button>
            )}
            {(st === 'accepted' || st === 'overridden') && statusLabel ? (
              <Badge type={st}>{statusLabel}</Badge>
            ) : null}
          </div>
        </div>
      ) : (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px',
          borderBottom: '1px solid var(--border)',
          background: `linear-gradient(135deg, ${borderAccent}06, transparent 60%)`,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.5, flex: '1 1 200px', minWidth: 0 }}>{q.text}</div>
              {q.fromApi && (q.srcs || []).filter(s => s.type !== 'none').length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', flexShrink: 0 }}>
                  {(q.srcs || []).filter(s => s.type !== 'none').map(s => (
                    <button
                      key={s.type}
                      type="button"
                      onClick={() => citationList.length > 0 && setActiveTab('sources')}
                      disabled={citationList.length === 0}
                      title={citationList.length > 0 ? 'View source excerpts' : undefined}
                      style={{
                        padding: 0,
                        border: 'none',
                        background: 'transparent',
                        cursor: citationList.length > 0 ? 'pointer' : 'default',
                        fontFamily: 'var(--font)',
                      }}
                    >
                      <AssistSourceChip s={s} minimal />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
              {q.srcs.filter(s => s.type !== 'none').map(s => (
                <span key={s.name} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600,
                  padding: '4px 10px 4px 6px', borderRadius: 20, background: `${s.color}12`, border: `1px solid ${s.color}30`,
                  color: s.color, lineHeight: 1,
                }}>
                  <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: '50%', background: '#fff', border: `1px solid ${s.color}20`, flexShrink: 0 }}>
                    <SourceIcon type={s.type} size={13} />
                  </span>
                  {s.name}
                </span>
              ))}
              {q.conflicts?.length >= 2 && (
                <button
                  type="button"
                  onClick={() => setConflictOpen(true)}
                  aria-label={`Open conflict options (${q?.conflicts?.length ?? 0})`}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700,
                    padding: '4px 10px', borderRadius: 20, background: 'rgba(234,88,12,.08)', border: '1px solid rgba(234,88,12,.25)',
                    color: '#EA580C', lineHeight: 1,
                    cursor: 'pointer',
                    fontFamily: 'var(--font)',
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#EA580C" strokeWidth="2.5" strokeLinecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  Conflict · {q?.conflicts?.length ?? 0} options
                </button>
              )}
            </div>
            {answerNotProvided && (
              <div role="status" style={{ fontSize: 11, fontWeight: 600, color: '#B91C1C', marginTop: 8, lineHeight: 1.45 }}>
                Answer not given — no extracted or entered response for this question yet.
              </div>
            )}
            {isSubmittedLocked && (
              <div role="status" style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginTop: 8, lineHeight: 1.45 }}>
                This answer has already been submitted and cannot be edited.
              </div>
            )}
          </div>
          {(visualStatus === 'accepted' || visualStatus === 'overridden') && statusLabel ? (
            <Badge type={visualStatus}>{statusLabel}</Badge>
          ) : null}
        </div>
      )}

      {/* ── Tab bar ────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: '1px solid rgba(15,23,42,.08)',
        background: assist ? '#fff' : 'var(--bg3)',
        padding: assist ? '0 12px' : '0 12px',
      }}>
        {tabs.map(tab => {
          const isActive = activeTab === tab.id
          const dot = (tab.id === 'feedback' && hasFeedback)
            || (tab.id === 'edit' && hasEdit)
          const activeBorder = SI_NAVY
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: assist ? 4 : 5, padding: assist ? '7px 12px' : '9px 14px',
                border: 'none', borderBottom: isActive ? `2px solid ${activeBorder}` : '2px solid transparent',
                marginBottom: -1,
                background: 'transparent', cursor: 'pointer', fontFamily: 'var(--font)',
                transition: 'all .12s',
              }}
            >
              {!assist && <span style={{ fontSize: 12, opacity: isActive ? 1 : .6 }}>{tab.icon}</span>}
              <span style={{ fontSize: assist ? 12 : 11, fontWeight: isActive ? 700 : 500, color: isActive ? SI_NAVY : 'var(--text2)' }}>
                {tab.label}
              </span>
              {dot && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--emerald)', flexShrink: 0 }} />}
            </button>
          )
        })}
      </div>

      {/* ── Tab content ────────────────────────────────────── */}
      <div style={{ padding: assist ? '10px 14px 12px' : '16px 18px', minHeight: assist ? 0 : 120, background: assist ? '#fff' : undefined }}>

        {/* ─── REVIEW tab ──────────────────────────────────── */}
        {activeTab === 'review' && (
          <>
            {assist ? (
              <div style={{
                borderRadius: 10,
                padding: '10px 12px 10px',
                marginBottom: 8,
                background: visualStatus === 'accepted' ? 'rgba(63,185,80,.07)' : visualStatus === 'overridden' ? 'rgba(250,204,21,.08)' : '#F4F5F7',
                border: `1px solid ${visualStatus === 'accepted' ? 'rgba(63,185,80,.25)' : visualStatus === 'overridden' ? 'rgba(234,179,8,.28)' : 'rgba(15,23,42,.08)'}`,
              }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
                  marginBottom: 6, flexWrap: 'wrap',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
                    {!backendAnswerInvalid ? (
                      <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.14em', color: SI_NAVY }}>
                        {reviewHeading}
                      </span>
                    ) : assistUserHasAnyResponse ? (
                      <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.14em', color: SI_NAVY }}>
                        {reviewHeading}
                      </span>
                    ) : (
                      <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '.12em', color: 'var(--text3)' }}>
                        NO EXTRACTED ANSWER
                      </span>
                    )}
                  </div>
                  {!assistAnswerStructured && !assistTextEditing && !isReadOnly && !hasUnresolvedConflict ? (
                    <button
                      type="button"
                      onClick={() => {
                        if (isAcceptedLike) {
                          onUndo?.(q.id)
                          setEditText(formatAnswerForDisplay(displayAnswerResolved != null ? String(displayAnswerResolved) : String(q.answer ?? '')))
                        }
                        setAssistTextEditing(true)
                      }}
                      style={{
                        flexShrink: 0,
                        padding: '6px 12px',
                        borderRadius: 8,
                        fontSize: 11,
                        fontWeight: 700,
                        fontFamily: 'var(--font)',
                        cursor: 'pointer',
                        border: `1px solid ${SI_NAVY}`,
                        background: '#fff',
                        color: SI_NAVY,
                      }}
                    >
                      Edit
                    </button>
                  ) : null}
                </div>
                {assistAnswerStructured ? (
                  assistAnswerStructured.showMulti ? (
                    <ReviewMultiCheckboxes
                      options={assistAnswerStructured.opts}
                      value={multiCheckboxValue}
                      payloadHighlightIds={payloadHighlightOptionIds}
                      onChange={handleAssistMultiSelection}
                      error={null}
                      disabled={assistControlsDisabled}
                      noTopMargin
                    />
                  ) : (
                    <ReviewPicklistRadios
                      name={`assist-pick-${q.id}`}
                      options={assistAnswerStructured.opts}
                      value={pickRadioValue}
                      payloadHighlightIds={payloadHighlightOptionIds}
                      onChange={handleAssistPickSelection}
                      error={null}
                      disabled={assistControlsDisabled}
                      noTopMargin
                    />
                  )
                ) : assistTextEditing ? (
                  <div>
                    <textarea
                      value={editText}
                      onChange={e => {
                        setEditText(e.target.value)
                        onDraftAnswerChange?.(q.id, e.target.value)
                      }}
                      placeholder="Edit the answer…"
                      style={{
                        ...txStyle,
                        minHeight: 100,
                        background: '#fff',
                        border: '1px solid rgba(15,23,42,.12)',
                      }}
                      onFocus={focusRing}
                      onBlur={blurRing}
                      disabled={isReadOnly}
                    />
                    <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                      <Btn
                        primary
                        disabled={isReadOnly}
                        onClick={() => {
                          onSaveEdit?.(q.id, editText)
                          setAssistTextEditing(false)
                        }}
                      >
                        Save changes
                      </Btn>
                      <Btn
                        ghost
                        onClick={() => {
                          setEditText(formatAnswerForDisplay(displayAnswerResolved != null ? String(displayAnswerResolved) : String(q.answer ?? '')))
                          setAssistTextEditing(false)
                        }}
                      >
                        Cancel
                      </Btn>
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      fontSize: 13,
                      color: '#1e293b',
                      lineHeight: 1.75,
                      whiteSpace: 'pre-wrap',
                      minHeight: answerNotProvided && !assistTextEditing ? 20 : undefined,
                    }}
                  >
                    {answerNotProvided && !assistTextEditing ? '' : displayAnswerResolved}
                  </div>
                )}
              </div>
            ) : null}

            {assist ? null : (
              <div style={{
                borderRadius: 10, padding: '12px 14px', marginBottom: 12,
                background: visualStatus === 'accepted' ? 'rgba(63,185,80,.04)' : visualStatus === 'overridden' ? 'rgba(210,153,34,.04)' : 'var(--bg3)',
                border: `1px solid ${visualStatus === 'accepted' ? 'rgba(63,185,80,.20)' : visualStatus === 'overridden' ? 'rgba(210,153,34,.20)' : 'var(--border)'}`,
              }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 9, fontWeight: 800,
                  textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 8,
                  color: visualStatus === 'accepted' ? '#56D364' : visualStatus === 'overridden' ? '#E3B341' : 'var(--p)',
                  background: visualStatus === 'accepted' ? 'rgba(63,185,80,.08)' : visualStatus === 'overridden' ? 'rgba(210,153,34,.08)' : 'rgba(37,99,235,.08)',
                  padding: '3px 8px', borderRadius: 5,
                }}>
                  ✦{' '}
                  {hasEdit
                    ? 'Edited Answer'
                    : visualStatus === 'accepted'
                      ? 'Accepted Answer'
                      : visualStatus === 'overridden'
                        ? 'Overridden Answer'
                        : 'AI Answer'}
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text1)', lineHeight: 1.7 }}>{displayAnswerResolved}</div>
              </div>
            )}

            {visualStatus === 'overridden' && qState.override && (
              <div style={{ borderRadius: 10, padding: '12px 14px', marginBottom: 12, background: 'rgba(210,153,34,.04)', border: '1px solid rgba(210,153,34,.18)' }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 9, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.6px', color: '#E3B341', background: 'rgba(210,153,34,.08)', padding: '3px 8px', borderRadius: 5, marginBottom: 8 }}>
                  ✎ Override Saved
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text1)', lineHeight: 1.7 }}>{qState.override}</div>
              </div>
            )}

            {/* Conflict: clarify beside accept (count in button label) */}
            {q.conflicts?.length >= 2 && !qState.conflictResolved && !isReadOnly && !isAcceptedLike && (
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8, marginTop: assist ? 8 : 10,
              }}>
                <button
                  type="button"
                  onClick={() => setConflictOpen(true)}
                  aria-label={`Clarify conflict: ${q?.conflicts?.length ?? 0} competing answers`}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderRadius: 8,
                    background: '#FCE8E6', border: '1px solid rgba(185,28,28,.22)',
                    cursor: 'pointer', fontFamily: 'var(--font)', transition: 'all .15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = '#FAD4CF'; e.currentTarget.style.borderColor = 'rgba(185,28,28,.35)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = '#FCE8E6'; e.currentTarget.style.borderColor = 'rgba(185,28,28,.22)' }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#BE123C" strokeWidth="2.5" strokeLinecap="round" aria-hidden>
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, textAlign: 'left' }}>
                    <span style={{ fontSize: 11, fontWeight: 800, color: '#9F1239', letterSpacing: '0.02em' }}>
                      Clarify conflict
                    </span>
                    <span style={{ fontSize: 10, fontWeight: 600, color: '#BE123C', opacity: 0.92 }}>
                      {q?.conflicts?.length ?? 0} competing answers — pick one to continue (Accept is disabled until resolved)
                    </span>
                  </span>
                </button>
                {shouldShowConflictNoSourcesInfo ? (
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 500,
                      color: 'var(--text3)',
                      lineHeight: 1.4,
                    }}
                  >
                    This conflict does not have a source.
                  </div>
                ) : null}
              </div>
            )}

            {q.conflicts?.length >= 2 && qState.conflictResolved && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontWeight: 600, color: '#16A34A', padding: '6px 0', flexWrap: 'wrap' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#16A34A" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                  Conflict resolved — selected response applied
                </span>
                {!isReadOnly && !isAcceptedLike ? (
                  <button
                    type="button"
                    onClick={() => setConflictOpen(true)}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 7,
                      border: '1px solid rgba(22,163,74,.25)',
                      background: 'rgba(22,163,74,.08)',
                      color: '#15803D',
                      fontSize: 10,
                      fontWeight: 700,
                      cursor: 'pointer',
                      fontFamily: 'var(--font)',
                    }}
                  >
                    Edit conflict choice
                  </button>
                ) : null}
              </div>
            )}

            {assist && st === 'pending' && !isReadOnly && (
              <div style={{ marginTop: 8 }}>
                <Btn
                  {...(assist ? { orangeOutline: true } : { green: true })}
                  onClick={() => {
                    console.log('[BUTTON CLICKED]', q.id)
                    handleAssistAccept()
                  }}
                  disabled={shouldDisableSingleAccept}
                  title={
                    hasUnresolvedConflict
                      ? 'Resolve conflict before accepting this answer'
                      : !hasValidDisplayAnswer
                        ? 'Select or enter an answer before accepting'
                        : undefined
                  }
                >
                  ✓ {acceptBtnLabel}
                </Btn>
              </div>
            )}

          </>
        )}

        {/* ─── Sources tab (GET /answers citations + relevance) ───── */}
        {activeTab === 'sources' && (
          <div>
            {citationList.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text2)', padding: '12px 0', lineHeight: 1.55 }}>
                No citations in the API payload for this question yet. When the backend returns a non-empty <code style={{ fontSize: 11 }}>citations[]</code> array, excerpts appear here.
              </div>
            ) : q.fromApi ? (
              <SourcesGroupedPanel citations={sortedCitationList} />
            ) : (
              sortedCitationList.map((c, i) => (
                <CitationBlock key={c.chunk_id || `c-${i}`} citation={c} index={i} />
              ))
            )}
          </div>
        )}

        {/* ─── EDIT tab (non-assist layout only) ───────────── */}
        {!assist && activeTab === 'edit' && (
          <>
            <div style={{ marginBottom: 10 }}>
              <label style={{ ...labelStyle }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2" strokeLinecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                Edit Answer
                <span style={{ fontWeight: 400, color: 'var(--text3)', textTransform: 'none', letterSpacing: 0 }}>— modify the AI-generated answer directly</span>
              </label>
              <textarea value={editText} onChange={e => {
                setEditText(e.target.value)
                onDraftAnswerChange?.(q.id, e.target.value)
              }}
                placeholder="Edit the answer text..."
                style={{ ...txStyle, minHeight: 100 }}
                onFocus={focusRing} onBlur={blurRing}
                disabled={isReadOnly}
              />
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <Btn primary disabled={isReadOnly} onClick={() => { onSaveEdit(q.id, editText); }}>Save Changes</Btn>
              <Btn ghost disabled={isReadOnly} onClick={() => setEditText(formatAnswerForDisplay(q.answer))}>Reset to Original</Btn>
              {hasEdit && <span style={{ fontSize: 10, color: 'var(--emerald)', fontWeight: 600, marginLeft: 4 }}>✓ Edited</span>}
            </div>
          </>
        )}

        {/* ─── FEEDBACK tab ────────────────────────────────── */}
        {activeTab === 'feedback' && (
          <>
            {!feedbackLocked ? (
              <>
                <div style={{ marginBottom: 14 }}>
                  <div style={{ ...labelStyle, marginBottom: 10 }}>
                    Rate AI Answer Quality
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {[1, 2, 3, 4, 5].map(star => {
                      const selected = fbVote === star
                      const filled = fbVote && star <= fbVote
                      return (
                        <button key={star} onClick={() => setFbVote(v => v === star ? null : star)}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: 4,
                            fontSize: 28,
                            color: filled ? '#F59E0B' : '#D1D5DB',
                            transition: 'all .15s',
                            transform: selected ? 'scale(1.1)' : 'scale(1)',
                          }}
                          onMouseEnter={(e) => {
                            if (!filled) {
                              e.target.style.color = '#FCD34D'
                              e.target.style.transform = 'scale(1.1)'
                            }
                          }}
                          onMouseLeave={(e) => {
                            if (!filled) {
                              e.target.style.color = '#D1D5DB'
                              e.target.style.transform = 'scale(1)'
                            }
                          }}
                        >
                          {filled ? '★' : '☆'}
                        </button>
                      )
                    })}
                    {fbVote && (
                      <span style={{
                        fontSize: 12,
                        color: 'var(--text2)',
                        marginLeft: 8,
                        fontWeight: 500,
                      }}>
                        {fbVote === 5 ? 'Excellent' :
                         fbVote === 4 ? 'Good' :
                         fbVote === 3 ? 'Average' :
                         fbVote === 2 ? 'Poor' : 'Very Poor'}
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <label style={{ ...labelStyle, marginBottom: 6 }}>
                    Additional Comments <span style={{ fontWeight: 400, color: 'var(--text3)', textTransform: 'none', letterSpacing: 0 }}>(optional)</span>
                  </label>
                  <textarea value={fbText} onChange={e => setFbText(e.target.value)}
                    placeholder="What could be improved about this answer?"
                    style={{ ...txStyle, minHeight: 64 }}
                    onFocus={focusRing} onBlur={blurRing}
                  />
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <Btn
                    primary
                    onClick={() => {
                      onSaveFeedback(q.id, fbVote, fbText)
                      setFbSaved(true)
                      setTimeout(() => setFbSaved(false), 2000)
                    }}
                    disabled={fbVote === null}
                  >
                    Submit Feedback
                  </Btn>
                  {fbSaved && <span style={{ fontSize: 11, color: 'var(--emerald)', fontWeight: 600 }}>✓ Feedback submitted</span>}
                </div>
              </>
            ) : hasFeedbackValue ? (
              <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', background: 'var(--bg3)' }}>
                <div style={{ ...labelStyle, marginBottom: 10 }}>Saved Feedback</div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 24, color: '#F59E0B', marginBottom: 8 }}>
                  {[1, 2, 3, 4, 5].map(star => (
                    <span key={star}>{star <= Number(fbVote ?? 0) ? '★' : '☆'}</span>
                  ))}
                </div>
                {String(fbText || '').trim() ? (
                  <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{fbText}</div>
                ) : (
                  <div style={{ fontSize: 12, color: 'var(--text3)' }}>No comments added.</div>
                )}
              </div>
            ) : (
              <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', background: 'var(--bg3)', fontSize: 12, color: 'var(--text3)' }}>
                No feedback has been submitted for this answer yet.
              </div>
            )}
          </>
        )}

      </div>

      {/* ── Footer actions (always visible) ────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px',
        borderTop: '1px solid rgba(15,23,42,.08)',
        background: assist ? '#FAFBFC' : 'var(--bg3)',
      }}>
        {visualStatus === 'accepted' ? (
          <Btn ghost disabled={isReadOnly} onClick={() => onUndo(q.id)}>
            {isReadOnly ? 'Already Submitted' : 'Undo Accept'}
          </Btn>
        ) : visualStatus === 'overridden' ? (
          <>
            <Btn
              ghost
              disabled={isReadOnly}
              onClick={() => {
                onEditOverride?.(q.id)
                if (assist) {
                  setEditText(String(qState.override ?? ''))
                  setAssistTextEditing(true)
                  setActiveTab('review')
                } else {
                  setActiveTab('edit')
                }
              }}
            >
              Save Override
            </Btn>
            <Btn ghost disabled={isReadOnly} onClick={() => onUndo(q.id)}>
              {isReadOnly ? 'Already Submitted' : 'Undo'}
            </Btn>
          </>
        ) : null}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {hasFeedback && <span style={{ fontSize: 12 }} title="Feedback given">{qState.feedback}★</span>}
        </div>
      </div>

      <ConflictResolutionModal
        open={Boolean(conflictOpen && q.conflicts?.length >= 2)}
        onClose={() => setConflictOpen(false)}
        questionText={q.text}
        conflicts={q.conflicts}
        stepLabel={null}
        initialSelectedAnswer={
          qState.conflictResolved ? String(qState.editedAnswer ?? '').trim() || null : null
        }
        initialSelectedAnswerId={
          conflictSelectionHint != null &&
          !Array.isArray(conflictSelectionHint) &&
          String(conflictSelectionHint).trim() !== ''
            ? String(conflictSelectionHint).trim()
            : null
        }
        onConfirm={(chosen) => {
          if (isAcceptedLike || isReadOnly) return
          if (onResolveConflict) onResolveConflict(q.id, chosen)
          setConflictOpen(false)
        }}
      />
    </div>
  )
}

const labelStyle = {
  display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 700,
  color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.5px',
}
const txStyle = {
  width: '100%', background: 'var(--bg)', border: '1px solid var(--border)',
  borderRadius: 8, padding: '10px 12px', color: 'var(--text0)', fontSize: 12,
  resize: 'vertical', outline: 'none', minHeight: 56, lineHeight: 1.6,
  boxSizing: 'border-box', fontFamily: 'var(--font)',
  transition: 'border-color .15s, box-shadow .15s',
}
const focusRing = (e) => { e.target.style.borderColor = 'rgba(27,38,79,.35)'; e.target.style.boxShadow = '0 0 0 3px rgba(27,38,79,.08)' }
const blurRing  = (e) => { e.target.style.borderColor = 'var(--border)'; e.target.style.boxShadow = 'none' }

const BTN_ORANGE = 'var(--si-orange, #E8532E)'

function Btn({ children, onClick, ghost, green, amber, primary, orangeOutline, disabled }) {
  const [hov, setHov] = useState(false)
  const base = {
    padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none', transition: 'all .15s',
    fontFamily: 'var(--font)', display: 'inline-flex', alignItems: 'center', gap: 4,
    opacity: disabled ? 0.5 : 1,
    pointerEvents: 'auto',
    position: 'relative',
    zIndex: 2,
  }
  const s = ghost
    ? { background: hov ? 'rgba(27,38,79,.08)' : 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)' }
    : orangeOutline
    ? {
      background: hov ? 'rgba(232,83,46,.08)' : '#fff',
      color: BTN_ORANGE,
      border: `2px solid ${BTN_ORANGE}`,
      fontWeight: 800,
      padding: '7px 16px',
    }
    : green
    ? { background: hov ? 'rgba(63,185,80,.20)' : 'rgba(63,185,80,.10)', color: '#16A34A', border: '1px solid rgba(63,185,80,.30)', fontWeight: 700 }
    : amber
    ? { background: hov ? 'rgba(210,153,34,.20)' : 'rgba(210,153,34,.10)', color: '#D97706', border: '1px solid rgba(210,153,34,.30)' }
    : primary
    ? { background: hov ? 'var(--p2)' : 'var(--p)', color: '#fff', border: 'none', fontWeight: 700 }
    : {}
  return <button type="button" style={{ ...base, ...s }} onClick={disabled ? undefined : onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>{children}</button>
}