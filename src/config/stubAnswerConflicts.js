/**
 * When GET /answers returns empty `conflicts[]` for a question, we can merge in the
 * known competing extractions from the oid0009 reference export (sample form output).
 *
 * Only these QIDs get frontend conflicts — all others stay as returned by the API.
 *
 * - VITE_STUB_ANSWER_CONFLICTS=true  → merge when API sends no conflicts for a listed QID (demo / local only)
 * - VITE_STUB_ANSWER_CONFLICTS=false → never merge (default)
 * - unset → do not merge — only rows that already include conflicts[] / conflict_id from GET /answers show conflict UI
 */

import overrides from '../data/oid0009ConflictOverrides.json'

export function stubAnswerConflictsEnabled() {
  const v = import.meta.env.VITE_STUB_ANSWER_CONFLICTS
  if (v === 'false') return false
  if (v === 'true') return true
  return false
}

/** Raw conflict entries as in GET /answers (before normalizeConflictEntry). */
export function getFrontendConflictEntriesForQuestion(questionId) {
  const k = String(questionId ?? '')
  const block = overrides[k]
  if (!block || !Array.isArray(block.conflicts)) return []
  return block.conflicts
}

/** QIDs that have bundled override rows (for tooling / docs). */
export const FRONTEND_CONFLICT_QUESTION_IDS = Object.keys(overrides)
