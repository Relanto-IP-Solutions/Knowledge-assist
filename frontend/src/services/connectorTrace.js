/**
 * Connector API call tracer.
 *
 * Wrap any connector API call with traced() to get:
 *   - Coloured console output with timing and sequential op-id
 *   - In-memory ring buffer (last 40 entries) accessible via getTraceLog()
 *
 * Usage:
 *   export async function authorizeDrive(oid) {
 *     return traced('authorizeDrive', () => api.post(...).then(r => r.data))
 *   }
 */

let _seq = 0
const _log = []
const MAX_LOG = 40

/** Return a shallow copy of the current trace ring-buffer (newest first). */
export function getTraceLog() { return [..._log] }

/** Clear the ring buffer (useful in tests). */
export function clearTraceLog() { _log.length = 0 }

/**
 * Wrap an async connector API call with structured console tracing.
 *
 * @param {string}            name  Human label, e.g. 'authorizeDrive'
 * @param {() => Promise<T>}  fn    The actual API call (no args)
 * @returns {Promise<T>}
 */
export async function traced(name, fn) {
  const opId = String(++_seq).padStart(3, '0')
  const t0 = performance.now()

  const entry = {
    opId,
    name,
    status: 'loading',
    startedAt: Date.now(),
    ms: null,
    response: null,
    error: null,
  }
  _log.unshift(entry)
  if (_log.length > MAX_LOG) _log.pop()

  console.log(
    `%c[connector]%c #${opId} ▶ ${name}`,
    'color:#4285F4;font-weight:700',
    'color:#64748B',
  )

  try {
    const result = await fn()
    entry.status = 'success'
    entry.response = result
    entry.ms = Math.round(performance.now() - t0)
    console.log(
      `%c[connector]%c #${opId} ✓ ${name}  ${entry.ms}ms`,
      'color:#10B981;font-weight:700',
      'color:#64748B',
      result,
    )
    return result
  } catch (e) {
    entry.status = 'error'
    entry.error = {
      httpStatus: e?.response?.status ?? null,
      detail: e?.response?.data ?? e?.message ?? String(e),
    }
    entry.ms = Math.round(performance.now() - t0)
    console.error(
      `[connector] #${opId} ✗ ${name}  ${entry.ms}ms`,
      entry.error,
    )
    throw e
  }
}

/**
 * Log an explicit skip — call whenever a connector API call is intentionally
 * not made, so "missing call" can be explained in the audit trail.
 *
 * @param {string} name    The call that was skipped
 * @param {string} reason  Why it was skipped
 */
export function traceSkip(name, reason) {
  const entry = {
    opId: `S${++_seq}`,
    name,
    status: 'skipped',
    reason,
    startedAt: Date.now(),
    ms: 0,
    response: null,
    error: null,
  }
  _log.unshift(entry)
  if (_log.length > MAX_LOG) _log.pop()
  console.info(
    `%c[connector]%c skip ${name}:`,
    'color:#F59E0B;font-weight:700',
    'color:#64748B',
    reason,
  )
}
