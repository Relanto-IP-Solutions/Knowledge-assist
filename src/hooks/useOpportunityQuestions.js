import { useCallback, useEffect, useState } from 'react'
import { fetchOpportunityQuestions } from '../services/opportunityReviewApi'

export function useOpportunityQuestions(opportunityId, options = {}) {
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
      const json = await fetchOpportunityQuestions(opportunityId, { bypassCache })
      setData(json)
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

