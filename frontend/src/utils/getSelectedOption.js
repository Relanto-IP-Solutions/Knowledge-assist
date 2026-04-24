function normalizeOptionLabel(option) {
  return String(option?.label ?? option?.text ?? option?.value ?? option?.id ?? '').trim()
}

/**
 * Safe picklist selection resolver for review UI.
 * Source of truth is always answer_value (display label), not cached ids.
 */
export function getSelectedOption(options, answer_value) {
  const needle = String(answer_value ?? '').trim()
  if (!needle || !Array.isArray(options)) return null

  const exact = options.find((opt) => String(opt?.label ?? '').trim() === needle)
  if (exact) return exact

  const byNormalizedLabel = options.find((opt) => normalizeOptionLabel(opt) === needle)
  if (byNormalizedLabel) return byNormalizedLabel

  const lowerNeedle = needle.toLowerCase()
  const caseInsensitive = options.find(
    (opt) => normalizeOptionLabel(opt).toLowerCase() === lowerNeedle,
  )
  return caseInsensitive || null
}

export function getOptionDisplayLabel(option) {
  return normalizeOptionLabel(option)
}
