import { useCallback, useEffect, useRef, useState } from 'react'
import { getMyRequests } from '../services/requestsApi'

/**
 * Polls the current user's opportunity requests every intervalMs.
 * Fires a toast when a request transitions PENDING → APPROVED or REJECTED.
 */
export function useMyRequests(intervalMs = 10000) {
  const [toast, setToast] = useState(null) // { msg: string, type: 'request_approved' | 'request_rejected' }
  const prevStatusesRef = useRef(null)     // null = first fetch not done yet
  const timerRef = useRef(null)
  const toastTimerRef = useRef(null)

  const poll = useCallback(async () => {
    try {
      const reqs = await getMyRequests()

      if (prevStatusesRef.current === null) {
        // First fetch — record baseline without firing any toasts.
        prevStatusesRef.current = Object.fromEntries(reqs.map(r => [r.request_id, r.status]))
        return
      }

      let newToast = null
      for (const r of reqs) {
        const prev = prevStatusesRef.current[r.request_id]
        if (prev === 'PENDING' && r.status === 'APPROVED') {
          newToast = {
            msg: `Your request "${r.opportunity_title}" was approved!`,
            type: 'request_approved',
          }
        } else if (prev === 'PENDING' && r.status === 'REJECTED') {
          const reason = r.admin_remarks ? ` Reason: ${r.admin_remarks}` : ''
          newToast = {
            msg: `Your request "${r.opportunity_title}" was rejected.${reason}`,
            type: 'request_rejected',
          }
        }
      }
      prevStatusesRef.current = Object.fromEntries(reqs.map(r => [r.request_id, r.status]))

      if (newToast) {
        clearTimeout(toastTimerRef.current)
        setToast(newToast)
        toastTimerRef.current = setTimeout(() => setToast(null), 5000)
      }
    } catch {
      // Network failure — skip this tick silently.
    }
  }, [])

  useEffect(() => {
    poll()
    timerRef.current = setInterval(poll, intervalMs)
    return () => {
      clearInterval(timerRef.current)
      clearTimeout(toastTimerRef.current)
    }
  }, [poll, intervalMs])

  return { toast, clearToast: () => setToast(null) }
}
