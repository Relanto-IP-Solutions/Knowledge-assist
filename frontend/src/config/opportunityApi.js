/**
 * Maps UI opportunity ids to backend ids when they differ (e.g. {"oid0009":"oid0009"} is unnecessary).
 * Set VITE_OPPORTUNITY_ID_MAP as JSON: {"OID/112299":"opp_backend_id_2"}
 */
export function toApiOpportunityId(oppId) {
  const raw = import.meta.env.VITE_OPPORTUNITY_ID_MAP
  if (raw) {
    try {
      const map = JSON.parse(raw)
      if (map && typeof map === 'object' && map[oppId]) return String(map[oppId])
    } catch {
      /* ignore */
    }
  }
  return String(oppId)
    .trim()
    .replace(/^OID\//i, 'opp_id_')
    .replace(/\//g, '_')
    .toLowerCase()
}

/** Parses Vite env booleans (handles CRLF / spaces; only `true` was too strict on Windows). */
function viteEnvBool(value) {
  if (value == null || value === '') return false
  const s = String(value).trim().toLowerCase()
  return s === 'true' || s === '1' || s === 'yes' || s === 'on'
}

/** When true, Q&A loads answers from GET /opportunities/{id}/answers */
export function useOpportunityAnswersApi() {
  return viteEnvBool(import.meta.env.VITE_USE_OPPORTUNITY_ANSWERS_API)
}
