import { useState, useEffect, useCallback } from 'react'
import { fetchOpportunityAnswers, normalizeAnswerRow } from '../services/opportunityAnswersApi'

/**
 * @param {string|null|undefined} opportunityId - backend id
 * @param {{ enabled?: boolean }} [options]
 */
export function useOpportunityAnswers(opportunityId, options = {}) {
  const { enabled = true } = options
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async (bypassCache = false) => {
    if (!enabled || !opportunityId) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const json = await fetchOpportunityAnswers(opportunityId, { bypassCache })
      const oid = String(json.opportunity_id ?? opportunityId ?? '')
      const answers = (json.answers || []).map(r => normalizeAnswerRow(r, { opportunityId: oid }))
      setData({
        opportunity_id: json.opportunity_id ?? opportunityId,
        answers,
      })
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setLoading(false)
    }
  }, [enabled, opportunityId])

  useEffect(() => {
    load(false)
  }, [load])

  return { data, loading, error, refetch: () => load(true) }
}
