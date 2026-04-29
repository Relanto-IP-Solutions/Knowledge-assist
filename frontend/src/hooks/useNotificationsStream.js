import { useEffect, useRef } from 'react'
import { consumeNotificationsStream } from '../services/notificationsStream'

const LOG = (...args) => {
  if (import.meta.env.DEV || String(import.meta.env.VITE_DEBUG_NOTIFICATIONS || '').toLowerCase() === 'true') {
    console.info('[useNotificationsStream]', ...args)
  }
}

/**
 * Opens GET /notifications/stream while `enabled` and dispatches window CustomEvents:
 * - `ka:opportunity_request_created` — detail: server payload (admins)
 * - `ka:opportunity_request_reviewed` — detail: server payload (requester)
 */
export function useNotificationsStream(enabled) {
  const runIdRef = useRef(0)

  useEffect(() => {
    if (!enabled) {
      LOG('disabled, skip SSE')
      return undefined
    }

    const ac = new AbortController()
    const myRun = ++runIdRef.current
    LOG('enabled, starting loop run=', myRun)

    const loop = async () => {
      while (!ac.signal.aborted && myRun === runIdRef.current) {
        try {
          await consumeNotificationsStream({
            signal: ac.signal,
            onMessage: (data) => {
              const t = data?.type
              if (t === 'opportunity_request.created') {
                window.dispatchEvent(new CustomEvent('ka:opportunity_request_created', { detail: data }))
              } else if (t === 'opportunity_request.reviewed') {
                window.dispatchEvent(new CustomEvent('ka:opportunity_request_reviewed', { detail: data }))
              }
            },
          })
        } catch (e) {
          if (ac.signal.aborted) {
            LOG('aborted')
          } else {
            LOG('stream error, will retry', e?.message || e)
          }
        }
        if (ac.signal.aborted || myRun !== runIdRef.current) break
        await new Promise((r) => setTimeout(r, 2000))
      }
    }

    void loop()
    return () => {
      LOG('cleanup abort run=', myRun)
      ac.abort()
    }
  }, [enabled])
}
