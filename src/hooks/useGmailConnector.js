/**
 * useGmailConnector
 *
 * Gmail mailbox identity is **per opportunity** (Sources page): separate localStorage + session keys per `opportunityId`.
 * Used for POST connect `user_email`, metrics `?user_email=`, and OAuth return prefetch.
 */

import { useState, useCallback, useEffect } from 'react'
import {
  startGmailDiscover,
  connectGmail,
  fetchGmailConnectInfo,
  fetchGmailMetrics,
  getGmailBackendRedirectUri,
  getGmailFrontendResultUrl,
  getGmailSourcesReturnUrl,
} from '../services/integrationsAuthApi'

/** Legacy single-mailbox session mirror (fallback after OAuth) */
export const GMAIL_CONNECTOR_EMAIL_SESSION_KEY = 'pzf_gmail_connector_email'

/** Session key for metrics prefetch on `/gmail-result` for this opportunity */
export function gmailConnectorEmailSessionKey(opportunityId) {
  return `pzf_gmail_connector_email__${encodeURIComponent(String(opportunityId))}`
}

function identityStorageKey(opportunityId) {
  return `pzf_gmail_connector_identity__${encodeURIComponent(String(opportunityId))}`
}

function loadScopedIdentity(opportunityId) {
  try {
    return JSON.parse(localStorage.getItem(identityStorageKey(opportunityId)) || 'null')
  } catch {
    return null
  }
}

function persistScopedIdentity(opportunityId, identity) {
  try {
    localStorage.setItem(identityStorageKey(opportunityId), JSON.stringify(identity))
    if (identity?.userEmail) {
      sessionStorage.setItem(gmailConnectorEmailSessionKey(opportunityId), identity.userEmail)
      sessionStorage.setItem(GMAIL_CONNECTOR_EMAIL_SESSION_KEY, identity.userEmail)
    } else {
      sessionStorage.removeItem(gmailConnectorEmailSessionKey(opportunityId))
    }
  } catch { /**/ }
}

/** Last opportunity id the user opened (OID card context) */
export const GMAIL_SELECTED_OID_SESSION_KEY = 'pzf_selected_oid'
/** After connect OAuth redirect, OID card resumes polling when this matches current oid */
export const GMAIL_RESUME_POLL_OID_KEY = 'pzf_gmail_resume_poll_oid'

/**
 * @param {string} opportunityId — backend opportunity id (scopes stored Gmail address to this project)
 */
export function useGmailConnector(opportunityId) {
  const [identity, setIdentityState] = useState(() => loadScopedIdentity(opportunityId))

  useEffect(() => {
    setIdentityState(loadScopedIdentity(opportunityId))
  }, [opportunityId])

  const setIdentity = useCallback((email) => {
    const id = { userEmail: email.trim().toLowerCase(), selectedAt: new Date().toISOString() }
    persistScopedIdentity(opportunityId, id)
    setIdentityState(id)
    return id
  }, [opportunityId])

  const clearIdentity = useCallback(() => {
    try {
      localStorage.removeItem(identityStorageKey(opportunityId))
      sessionStorage.removeItem(gmailConnectorEmailSessionKey(opportunityId))
    } catch { /**/ }
    setIdentityState(null)
  }, [opportunityId])

  /**
   * POST /integrations/gmail/discover — include `oid` and optional `user_email` (after user enters mailbox).
   */
  const discover = useCallback(async (options = {}) => {
    const payload = {
      redirect_uri: getGmailBackendRedirectUri(),
      return_url: getGmailFrontendResultUrl(),
    }
    const oid = options.oid != null && String(options.oid).trim() !== '' ? String(options.oid).trim() : null
    if (oid) {
      payload.oid = oid
      payload.return_url = getGmailSourcesReturnUrl(oid)
    }
    const ue = options.userEmail != null && String(options.userEmail).trim() !== '' ? String(options.userEmail).trim().toLowerCase() : ''
    if (ue) payload.user_email = ue
    return startGmailDiscover(payload)
  }, [])

  const connect = useCallback(async (oid) => {
    if (!identity?.userEmail) {
      const e = new Error('Enter the Gmail address for this opportunity first.')
      e.code = 'NO_IDENTITY'
      throw e
    }
    return connectGmail(oid, getGmailBackendRedirectUri(), identity.userEmail, getGmailSourcesReturnUrl(oid))
  }, [identity])

  const getConnectInfo = useCallback((oid) => fetchGmailConnectInfo(oid), [])

  const getMetrics = useCallback(
    (oid) => fetchGmailMetrics(oid, identity?.userEmail),
    [identity?.userEmail]
  )

  return {
    identity,
    setIdentity,
    clearIdentity,
    discover,
    connect,
    getConnectInfo,
    getMetrics,
  }
}
