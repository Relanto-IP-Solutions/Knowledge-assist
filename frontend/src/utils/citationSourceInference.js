/**
 * When GET /answers omits or sends `source_type: "unknown"`, infer from path/name
 * (e.g. …/zoom_transcripts/… → zoom) so the UI shows Zoom / file names instead of generic labels.
 */

/**
 * @param {{ source_type?: unknown, source_file?: unknown, source_name?: unknown }} c
 * @returns {string} normalized type string (may still be "unknown")
 */
export function inferSourceTypeFromCitationFields(c) {
  const raw = c?.source_type != null ? String(c.source_type).trim() : ''
  if (raw && raw.toLowerCase() !== 'unknown') return raw

  const f = String(c?.source_file ?? '').toLowerCase()
  const n = String(c?.source_name ?? c?.source_document ?? '').toLowerCase()

  if (f.includes('zoom_transcript') || f.includes('zoom_transcripts') || f.includes('/zoom/')) return 'zoom'
  if (
    f.includes('slack_messages') ||
    f.includes('/slack/') ||
    f.includes('slack_export') ||
    f.includes('slack-') ||
    n.includes('slack')
  )
    return 'slack'
  if (f.includes('gmail') || f.includes('mail_message')) return 'gmail'
  if (f.includes('google_drive') || f.includes('gdrive') || f.includes('/drive/')) return 'gdrive'
  if (
    f.endsWith('.docx') ||
    n.endsWith('.docx') ||
    f.includes('word_docs') ||
    f.includes('word_doc') ||
    f.includes('wordprocessingml') ||
    f.includes('msword') ||
    f.includes('contracts/') ||
    f.includes('document.docx')
  )
    return 'gdrive'

  return raw || 'unknown'
}

/**
 * @typedef {'zoom'|'docx'|'slack'|'gdrive'|'gmail'|'other'} CitationBucket
 */

/**
 * UI bucket for Sources tab (separate sections). Docx is split from generic Drive when path/name says .docx.
 * @param {Record<string, unknown>} c
 * @returns {CitationBucket}
 */
export function citationBucket(c) {
  if (c == null || typeof c !== 'object') return 'other'
  const merged = inferSourceTypeFromCitationFields({
    source_type: c.source_type,
    source_file: c.source_file,
    source_name: c.source_name ?? c.source_document,
  })
  const f = String(c.source_file ?? '').toLowerCase()
  const n = String(c.source_name ?? c.source_document ?? '').toLowerCase()
  const st = String(merged ?? '').toLowerCase()

  if (st.includes('zoom') || f.includes('zoom_transcript') || f.includes('zoom_transcripts') || f.includes('/zoom/')) return 'zoom'

  const isDocx =
    f.endsWith('.docx') ||
    n.endsWith('.docx') ||
    f.includes('word_docs') ||
    f.includes('word_doc') ||
    f.includes('wordprocessingml') ||
    f.includes('msword') ||
    f.includes('contracts/') ||
    st.includes('docx') ||
    st.includes('wordprocessingml')
  if (isDocx) return 'docx'

  if (
    st.includes('slack') ||
    f.includes('slack_messages') ||
    f.includes('/slack/') ||
    f.includes('slack_export') ||
    n.includes('slack')
  )
    return 'slack'

  if (st.includes('gmail') || f.includes('gmail') || f.includes('mail_message')) return 'gmail'

  if (st.includes('gdrive') || st.includes('google_drive') || st.includes('drive_doc') || f.includes('/drive/') || f.includes('gdrive'))
    return 'gdrive'

  return 'other'
}

/** @typedef {'zoom'|'docx'|'slack'|'gdrive'|'gmail'|'other'} CitationBucket */

export const CITATION_BUCKET_ORDER = /** @type {const} */ ([
  'zoom',
  'docx',
  'slack',
  'gdrive',
  'gmail',
  'other',
])

/**
 * @param {Record<string, unknown>[]} citations
 * @returns {Record<CitationBucket, Record<string, unknown>[]>}
 */
export function groupCitationsByBucket(citations) {
  /** @type {Record<CitationBucket, Record<string, unknown>[]>} */
  const groups = {
    zoom: [],
    docx: [],
    slack: [],
    gdrive: [],
    gmail: [],
    other: [],
  }
  for (const c of citations) {
    const k = citationBucket(c)
    groups[k].push(c)
  }
  return groups
}

/**
 * @param {CitationBucket} key
 */
export function citationSectionTitle(key) {
  const m = {
    zoom: 'Zoom transcripts',
    docx: 'Word documents (DOCX)',
    slack: 'Slack messages',
    gdrive: 'Google Drive',
    gmail: 'Gmail',
    other: 'Other sources',
  }
  return m[key] || m.other
}

/**
 * @param {string} labelish
 * @returns {string} short display label (never empty)
 */
export function citationDisplayLabelFallback(c) {
  if (c == null || typeof c !== 'object') return 'Evidence'
  const st = c.source_type != null ? String(c.source_type).trim() : ''
  if (st && st.toLowerCase() !== 'unknown') {
    return st.replace(/_/g, ' ')
  }
  const name = String(c.source_name ?? c.source_document ?? '').trim()
  if (name) return name.length > 48 ? `${name.slice(0, 45)}…` : name
  const path = String(c.source_file ?? '').trim()
  if (path) {
    const seg = path.split(/[/\\]/).filter(Boolean)
    const base = seg.length ? seg[seg.length - 1] : path
    return base.length > 48 ? `${base.slice(0, 45)}…` : base
  }
  return 'Evidence'
}
