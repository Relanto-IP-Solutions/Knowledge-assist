import { api } from './apiClient'

let inflight = null
let cache = null

/**
 * GET /opportunities/ids
 * Expected shapes (we accept a few variants):
 * - `[{ opportunity_id, name }]`
 * - `{ opportunities: [{ opportunity_id, name }] }`
 * - `{ ids: [{ opportunity_id, name }] }`
 *
 * @returns {Promise<Array<{opportunity_id: string, name: string}>>}
 */
export async function fetchOpportunityIds(options = {}) {
  const { bypassCache = false } = options
  if (!bypassCache && Array.isArray(cache)) return cache
  if (!bypassCache && inflight) return inflight

  const url = '/opportunities/ids'
  const debugUrl = `${String(api.defaults.baseURL || '').replace(/\/$/, '')}${url}`
  const p = (async () => {
    try {
      const { data: json } = await api.get(url)
      const list = Array.isArray(json)
        ? json
        : Array.isArray(json?.opportunities)
          ? json.opportunities
          : Array.isArray(json?.ids)
            ? json.ids
            : []
      const passthroughKeys = [
        'owner_id',
        'is_active',
        'status',
        'completion',
        'total_questions',
        'ai_count',
        'human_count',
        'percentage',
        'ai_percentage',
        'human_percentage',
        'organization_name',
        'project_line',
        'projectLine',
        'conflict_message',
        'conflictMessage',
      ]
      cache = list
        .filter(x => x && typeof x === 'object')
        .map(x => {
          const opportunity_id = String(x.opportunity_id ?? x.opportunityId ?? x.id ?? '').trim()
          const name = String(x.name ?? x.opportunity_name ?? x.opportunityName ?? '').trim()
          /** @type {Record<string, unknown>} */
          const row = { opportunity_id, name }
          for (const k of passthroughKeys) {
            if (x[k] !== undefined && x[k] !== null) row[k] = x[k]
          }
          return row
        })
        .filter(x => x.opportunity_id)

      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / live API]%c GET /opportunities/ids',
          'color:#2563eb;font-weight:700',
          'color:inherit',
          debugUrl,
          cache,
        )
      }
      return cache
    } finally {
      inflight = null
    }
  })()

  inflight = p
  return p
}

export function clearOpportunityIdsCache() {
  cache = null
  inflight = null
}

