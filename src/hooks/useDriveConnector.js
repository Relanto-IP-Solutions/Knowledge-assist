/**
 * Per-opportunity Drive connector identity (Google account email for authorize-info + connect).
 * Mirrors {@link useGmailConnector} storage pattern.
 */

import { useState, useCallback, useEffect } from 'react'

function identityStorageKey(opportunityId) {
  return `pzf_drive_connector_identity__${encodeURIComponent(String(opportunityId))}`
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
  } catch { /**/ }
}

/**
 * @param {string} opportunityId — backend opportunity id (oid)
 */
export function useDriveConnector(opportunityId) {
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
    } catch { /**/ }
    setIdentityState(null)
  }, [opportunityId])

  return { identity, setIdentity, clearIdentity }
}
