/**
 * Opportunity lifecycle (verify paths against your Postman collection / OpenAPI).
 */

import { api } from './apiClient'

/**
 * Create a new opportunity.
 * POST /opportunities/create
 * @param {{ name: string }} input
 * @returns {Promise<{ opportunity_id: string, raw: unknown }>}
 */
export async function createOpportunity(input) {
  const name = String(input.name || '').trim()
  if (!name) throw new Error('Opportunity name is required')

  const payload = { name }

  try {
    const { data: json } = await api.post('/opportunities/create', payload, {
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

/**
 * Lock an opportunity (admin only).
 * POST /opportunities/{opportunity_id}/lock
 * Bearer token is auto-attached by apiClient interceptor.
 * @param {string} opportunityId
 * @returns {Promise<unknown>}
 */
export async function lockOpportunity(opportunityId) {
  const id = String(opportunityId || '').trim()
  if (!id) throw new Error('opportunity_id is required')
  try {
    const { data } = await api.post(`/opportunities/${encodeURIComponent(id)}/lock`, {
      opportunity_id: id,
    })
    return data
  } catch (e) {
    const status = e?.response?.status
    const detail =
      e?.response?.data?.detail ||
      (typeof e?.response?.data === 'string' ? e.response.data : null) ||
      e?.message ||
      'Failed to lock opportunity.'
    const err = new Error(detail)
    err.status = status
    throw err
  }
}
