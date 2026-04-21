/**
 * When GET /answers returns rows with no `citations[]` (e.g. catalog-only skeleton),
 * merge citations in this order (oid0009 only, when stubs enabled):
 * 1. Explicit `oid0009CitationOverrides.json` (e.g. QID-001 sample Zoom rows)
 * 2. First conflict option’s citations from `oid0009ConflictOverrides.json` (QIDs that have conflict stubs)
 * 3. A single placeholder row so the Sources tab isn’t empty for remaining QIDs
 *
 * When the API sends citations[], none of this runs.
 *
 * - VITE_STUB_ANSWER_CITATIONS=false → never merge (use when GET /answers returns real citations)
 * - unset or true                    → merge when API omits citations (default ON)
 */

import citationOverrides from '../data/oid0009CitationOverrides.json'
import conflictOverrides from '../data/oid0009ConflictOverrides.json'

function viteEnvBool(value, defaultWhenUnset) {
  if (value == null || value === '') return defaultWhenUnset
  const s = String(value).trim().toLowerCase()
  if (s === 'false' || s === '0' || s === 'no' || s === 'off') return false
  if (s === 'true' || s === '1' || s === 'yes' || s === 'on') return true
  return defaultWhenUnset
}

export function stubAnswerCitationsEnabled() {
  const raw = import.meta.env.VITE_STUB_ANSWER_CITATIONS
  if (raw != null && String(raw).trim() !== '') {
    return viteEnvBool(raw, true)
  }
  return true
}

function citationsFromFirstConflict(questionId) {
  const k = String(questionId ?? '')
  const block = conflictOverrides[k]
  if (!block || !Array.isArray(block.conflicts)) return null
  for (const c of block.conflicts) {
    if (c && Array.isArray(c.citations) && c.citations.length > 0) return c.citations
  }
  return null
}

/** One honest placeholder when no file-based stub exists (still shows Sources tab UX). */
function placeholderCitation(questionId) {
  return [
    {
      source_type: 'unknown',
      source_file: '',
      source_name: 'API — citations pending',
      chunk_id: `stub-placeholder-${String(questionId).replace(/[^\w-]/g, '')}`,
      quote:
        `GET /answers did not include a citations[] array for ${String(questionId)}. When the backend adds source excerpts, they will appear here.`,
      relevance_score: 0,
      is_primary: false,
    },
  ]
}

/**
 * Raw citation objects (before normalizeCitation) for this opportunity + question, or null.
 * @param {string} opportunityId
 * @param {string} questionId
 * @returns {unknown[] | null}
 */
export function getStubCitationsRawForQuestion(opportunityId, questionId) {
  if (!stubAnswerCitationsEnabled()) return null
  const oid = String(opportunityId ?? '').trim().toLowerCase()
  if (oid !== 'oid0009') return null
  const k = String(questionId ?? '')

  const explicit = citationOverrides[k]
  if (explicit && Array.isArray(explicit.citations) && explicit.citations.length > 0) {
    return explicit.citations
  }

  const fromConflict = citationsFromFirstConflict(k)
  if (fromConflict?.length) return fromConflict

  if (/^QID-\d+$/i.test(k)) return placeholderCitation(k)

  return null
}
