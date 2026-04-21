/** Source chips in conflict picker modals (maps classifyApiSourceType → UI). */
export const CONFLICT_SRC_MODAL = {
  zoom: { label: 'Zoom', color: '#2D8CFF', type: 'zoom' },
  gdrive: { label: 'Google Drive', color: '#34A853', type: 'gdrive' },
  gmail: { label: 'Gmail', color: '#EA4335', type: 'gmail' },
  slack: { label: 'Slack', color: '#E01E5A', type: 'slack' },
}

/**
 * @param {{ qid?: string, role?: string, conflictIndex?: number }} c
 * @param {{ omitQid?: boolean }} [opts]
 */
export function conflictOptionHeading(c, i, opts = {}) {
  const omitQid = Boolean(opts.omitQid)
  const qidPart = !omitQid && c.qid ? `${c.qid} · ` : ''
  const rest =
    c.role === 'primary'
      ? 'Primary recommendation'
      : c.role === 'conflict' && c.conflictIndex != null
        ? `Conflict ${c.conflictIndex}`
        : `Option ${i + 1}`
  return qidPart + rest
}
