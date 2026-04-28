import { parseSerializedListAnswerValue } from './opportunityAnswerRowToReviewQuestion'

function normalizeAnswerTypeKey(answerType) {
  return String(answerType ?? '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
}

function normalizeTextToken(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

function normalizeNumericToken(value) {
  if (value == null || String(value).trim() === '') return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return normalizeTextToken(value)
  return String(n)
}

function canonicalOptionToken(raw, options = []) {
  const source = String(raw ?? '').trim()
  if (!source) return ''
  const lower = source.toLowerCase()
  if (Array.isArray(options) && options.length > 0) {
    const match = options.find((option) => {
      const id = String(option?.id ?? '').trim()
      const text = String(option?.text ?? '').trim()
      const label = String(option?.label ?? '').trim()
      const value = String(option?.value ?? '').trim()
      return (
        id === source ||
        text === source ||
        text.toLowerCase() === lower ||
        label === source ||
        label.toLowerCase() === lower ||
        value === source ||
        value.toLowerCase() === lower
      )
    })
    if (match) {
      return normalizeTextToken(match.text ?? match.label ?? match.value ?? match.id ?? source)
    }
  }
  return normalizeTextToken(source)
}

function toTokens(value) {
  if (value == null) return []
  if (Array.isArray(value)) return value.map(v => String(v ?? '').trim()).filter(Boolean)
  const raw = String(value).trim()
  if (!raw) return []
  if (raw.startsWith('[')) {
    try {
      const parsed = parseSerializedListAnswerValue(raw)
      if (parsed.length > 0) return parsed.map(v => String(v ?? '').trim()).filter(Boolean)
    } catch {
      // Keep raw fallback below.
    }
  }
  if (raw.includes(',')) {
    const parts = raw.split(/,\s*/).map(v => v.trim()).filter(Boolean)
    if (parts.length > 1) return parts
  }
  return [raw]
}

export function normalizedAnswerKey(value, { answerType, options = [] } = {}) {
  const kind = normalizeAnswerTypeKey(answerType)
  const multi = kind === 'multi_select' || kind.includes('multi')
  const numeric = ['integer', 'number', 'decimal', 'float', 'double', 'int', 'bigint'].includes(kind)
  const baseTokens = toTokens(value)
  const normalized = baseTokens
    .map(token => {
      if (numeric) return normalizeNumericToken(token)
      if (multi) return canonicalOptionToken(token, options)
      return canonicalOptionToken(token, options)
    })
    .filter(Boolean)
  if (multi) return normalized.slice().sort().join('|')
  return normalized[0] ?? ''
}

export function areAnswersEquivalent(currentValue, aiValue, { answerType, options = [] } = {}) {
  return (
    normalizedAnswerKey(currentValue, { answerType, options }) ===
    normalizedAnswerKey(aiValue, { answerType, options })
  )
}

export function isAnswerOverride(currentValue, aiValue, { answerType, options = [] } = {}) {
  return !areAnswersEquivalent(currentValue, aiValue, { answerType, options })
}

export function isAnswerOverrideAgainstAny(currentValue, aiValues, { answerType, options = [] } = {}) {
  const candidates = Array.isArray(aiValues) ? aiValues : [aiValues]
  const normalizedCurrent = normalizedAnswerKey(currentValue, { answerType, options })
  if (!normalizedCurrent) return false
  for (const candidate of candidates) {
    const normalizedCandidate = normalizedAnswerKey(candidate, { answerType, options })
    if (normalizedCandidate && normalizedCandidate === normalizedCurrent) return false
  }
  return true
}
