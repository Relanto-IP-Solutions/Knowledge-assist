/**
 * Opportunity lifecycle (verify paths against your Postman collection / OpenAPI).
 */

import { api } from './apiClient'

/**
 * Create a new opportunity.
 * POST http://localhost:8000/opportunities/create
 * @param {{ name: string }} input
 * @returns {Promise<{ opportunity_id: string, raw: unknown }>}
 */
export async function createOpportunity(input) {
  const name = String(input.name || '').trim()
  if (!name) throw new Error('Opportunity name is required')

  const payload = { name }
  const url = 'http://localhost:8000/opportunities/create'

  try {
    const { data: json } = await api.post(url, payload, {
      headers: { 'Content-Type': 'application/json' },
    })
    const id = String(
      json?.opportunity_id ??
      json?.opportunityId ??
      json?.id ??
      json?.data?.opportunity_id,
    ).trim()
    if (!id) throw new Error('Create succeeded but no opportunity_id was returned')
    return { opportunity_id: id, raw: json }
  } catch (e) {
    const status = e?.response?.status
    const bodyText =
      typeof e?.response?.data === 'string'
        ? e.response.data
        : e?.response?.data != null
          ? JSON.stringify(e.response.data)
          : ''
    throw new Error(bodyText || e?.message || (status ? `HTTP ${status}` : 'Request failed'))
  }
}
