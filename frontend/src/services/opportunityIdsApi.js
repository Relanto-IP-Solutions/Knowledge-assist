import { api } from './apiClient'

const inflightByKey = new Map()
const cacheByKey = new Map()

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
  const {
    bypassCache = false,
    cacheKey = 'default',
    isAdmin = false,
    includeAllForAdmin = true,
  } = options
  const normalizedCacheKey = String(cacheKey || 'default').trim() || 'default'
  const useAdminScope = Boolean(isAdmin) && Boolean(includeAllForAdmin)
  const requestKey = `${normalizedCacheKey}|admin:${useAdminScope ? '1' : '0'}`
  if (!bypassCache && cacheByKey.has(requestKey)) return cacheByKey.get(requestKey)
  if (!bypassCache && inflightByKey.has(requestKey)) return inflightByKey.get(requestKey)

  const url = '/opportunities/ids'
  const params = useAdminScope ? { include_all: true } : undefined
  const debugUrl = `${String(api.defaults.baseURL || '').replace(/\/$/, '')}${url}`
  const p = (async () => {
    try {
      const { data: json } = await api.get(url, params ? { params } : undefined)
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
      const normalizedRows = list
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
      cacheByKey.set(requestKey, normalizedRows)

      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / live API]%c GET /opportunities/ids',
          'color:#2563eb;font-weight:700',
          'color:inherit',
          debugUrl,
          params || {},
          normalizedRows,
        )
      }
      return normalizedRows
    } finally {
      inflightByKey.delete(requestKey)
    }
  })()

  inflightByKey.set(requestKey, p)
  return p
}

export function clearOpportunityIdsCache() {
  cacheByKey.clear()
  inflightByKey.clear()
}

