import { useEffect, useState } from 'react'
import { listOpportunityRequests } from '../services/requestsApi'

/**
 * Returns { isAdmin: bool, loading: bool }.
 * Determines admin status by probing the admin-only requests endpoint once.
 * 403 → not admin; 200 → admin.
 */
export function useIsAdmin() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    listOpportunityRequests({ limit: 1 })
      .then(() => { if (!cancelled) setIsAdmin(true) })
      .catch(() => { if (!cancelled) setIsAdmin(false) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return { isAdmin, loading }
}
