/**
 * Maps backend Gmail API errors to user-friendly messages.
 * Spec: always show backend detail clearly for 400/404 errors.
 */

export const WORKSPACE_POLICY_ERROR_MSG =
  "It looks like your company's Google security settings are blocking this sync. Please contact your IT administrator to trust this application in the Google Admin Console."

export function isWorkspacePolicyError(error) {
  const status = error?.response?.status
  const detail = String(error?.response?.data?.detail ?? error?.response?.data?.message ?? error?.message ?? '').toLowerCase()
  return status === 403 && (detail.includes('workspace') || detail.includes('domain policy'))
}

export function mapGmailError(error) {
  const status    = error?.response?.status
  const detail    = error?.response?.data?.detail ?? error?.response?.data?.message ?? error?.message ?? ''
  const detailStr = String(detail).toLowerCase()

  if (!status && !detail) return 'An unexpected error occurred. Please try again.'

  // 400 — missing user_email (OID card uses email-only identity)
  if (status === 400) {
    if (!detailStr || detailStr.includes('user_email') || detailStr.includes('missing'))
      return 'Please select mailbox first.'
    return String(detail) || 'Invalid request. Please check your input.'
  }

  // 401 — not authenticated / token missing
  if (status === 401) return 'This mailbox is not authorized yet. Please complete Google authorization.'

  // 403 — workspace/domain policy block or wrong account / scope
  if (status === 403) {
    if (detailStr.includes('workspace') || detailStr.includes('domain policy'))
      return WORKSPACE_POLICY_ERROR_MSG
    if (detailStr.includes('mismatch') || detailStr.includes('different'))
      return String(detail).trim() || 'You logged in with a different Google account than the selected mailbox. Sign in with the selected mailbox.'
    if (detailStr.includes('scope'))
      return 'Gmail permission was not granted. Please re-authorize and allow the requested access.'
    return String(detail) || 'Access denied. Please re-authorize Gmail.'
  }

  // 404 — user not in users table, or no OID-matching threads, or unknown OID
  if (status === 404) {
    if (detailStr.includes('user') || detailStr.includes('not registered') || (detailStr.includes('email') && detailStr.includes('not')))
      return 'Entered mailbox is not onboarded in system.'
    if (detailStr.includes('thread') && (detailStr.includes('oid') || detailStr.includes('match')))
      return 'Connected, but no OID emails found.'
    if (detailStr.includes('opportunity') || detailStr.includes('oid'))
      return String(detail) || 'Opportunity not found. Make sure the OID exists before connecting Gmail.'
    return String(detail) || 'Not found. Please try again.'
  }

  // 422 — unprocessable / missing fields
  if (status === 422) return String(detail) || 'Missing required field. Please provide a valid Gmail address.'

  // Network error
  if (!status) {
    if (detailStr.includes('network') || detailStr.includes('econnrefused') || detailStr.includes('fetch'))
      return 'Cannot reach the server. Check your connection and try again.'
    return String(detail) || 'Network error. Please try again.'
  }

  // Fallback — use backend detail if available
  return String(detail) || `Server error (${status}). Please try again.`
}

/**
 * Returns true only when a 404 means "no OID-matching threads found" (discover ran OK, inbox just empty).
 * Does NOT catch user-not-found 404s.
 */
export function isEmptyDiscoverError(error) {
  const status = error?.response?.status
  const detail = String(error?.response?.data?.detail ?? '').toLowerCase()
  // Only treat as empty-discover if detail explicitly mentions threads or OIDs
  return status === 404 && (detail.includes('thread') || detail.includes('oid'))
}
