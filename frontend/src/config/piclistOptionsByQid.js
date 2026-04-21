import PICLIST_STUDIO_ROWS from './piclistStudioRows.json'

/**
 * Studio-exported piclist rows: { id, q_id, option_value, sort_order }.
 * Maps to QID-### so review UI can show full radios/checkboxes and submit answer_id.
 */

export function normalizeQuestionIdForPiclist(raw) {
  if (raw == null || raw === '') return ''
  const s = String(raw).trim().toUpperCase()
  let m = s.match(/^QID-(\d+)$/)
  if (!m) m = s.match(/^DOR-(\d+)$/i)
  if (!m) m = s.match(/^(\d+)$/)
  if (!m) return s
  const n = parseInt(m[1], 10)
  if (!Number.isFinite(n)) return s
  return `QID-${String(n).padStart(3, '0')}`
}

const BY_QID = new Map()

for (const row of PICLIST_STUDIO_ROWS) {
  const k = normalizeQuestionIdForPiclist(row.q_id)
  if (!k) continue
  if (!BY_QID.has(k)) BY_QID.set(k, [])
  BY_QID.get(k).push(row)
}

for (const arr of BY_QID.values()) {
  arr.sort((a, b) => {
    const so = Number(a.sort_order) - Number(b.sort_order)
    if (so !== 0) return so
    return Number(a.id) - Number(b.id)
  })
}

/** @returns {typeof PICLIST_STUDIO_ROWS} */
export function getPiclistStudioRowsForQuestion(rawQid) {
  const k = normalizeQuestionIdForPiclist(rawQid)
  return BY_QID.get(k) ?? []
}

/** @returns {{ answer_id: string, answer_value: string }[]} */
export function getPiclistAnswerRowsForQuestion(rawQid) {
  return getPiclistStudioRowsForQuestion(rawQid).map(r => {
    const text = String(r.option_value ?? '').trim()
    const id = String(r.id)
    return { answer_id: id, answer_value: text || id }
  })
}

/**
 * Map display text or legacy id string to the piclist row's canonical `answer_id` (row `id`), not `option_value`.
 * @returns {string|null}
 */
export function matchPiclistValueToAnswerId(rawQid, rawValue) {
  if (rawValue == null) return null
  const t = String(rawValue).trim()
  if (!t) return null
  const rows = getPiclistStudioRowsForQuestion(rawQid)
  if (!rows.length) return null
  for (const r of rows) {
    if (String(r.id) === t) return String(r.id)
  }
  const tl = t.toLowerCase()
  for (const r of rows) {
    if (String(r.option_value).trim().toLowerCase() === tl) return String(r.id)
  }
  return null
}
