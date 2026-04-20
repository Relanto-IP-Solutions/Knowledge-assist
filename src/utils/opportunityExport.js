/**
 * Client-side export helpers: CSV, Word-compatible HTML (.doc), and PDF download.
 */

import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'

function escapeCsvCell(s) {
  const t = String(s ?? '')
  if (/[",\n\r]/.test(t)) return `"${t.replace(/"/g, '""')}"`
  return t
}

function pickQuestionText(qRow, catalogByQid) {
  const fromCat = catalogByQid.get(String(qRow.question_id ?? ''))
  const t =
    fromCat?.question_text ??
    fromCat?.questionText ??
    qRow.question_text ??
    qRow.questionText ??
    ''
  return String(t).trim() || String(qRow.question_id ?? '')
}

function resolveOptionLabel(idRaw, cat) {
  const id = String(idRaw ?? '').trim()
  if (!id) return ''
  const opts = cat?.answers ?? cat?.answer_list ?? cat?.answer_options ?? cat?.options
  if (Array.isArray(opts)) {
    const hit = opts.find(
      o =>
        String(o?.answer_id ?? o?.id ?? '').trim() === id ||
        String(o?.answer_value ?? o?.text ?? o?.label ?? '').trim() === id,
    )
    if (hit) return String(hit.answer_value ?? hit.text ?? hit.label ?? id).trim()
  }
  return id
}

function pickAnswerDisplay(row, catalogByQid) {
  const qid = String(row.question_id ?? '')
  const cat = catalogByQid.get(qid)
  const raw =
    row.answer_value ??
    row.answerValue ??
    row.final_answer ??
    row.finalAnswer ??
    ''

  if (raw != null && String(raw).trim() !== '') {
    const s = String(raw).trim()
    if (s.startsWith('[')) {
      try {
        const arr = JSON.parse(s)
        if (Array.isArray(arr)) {
          return arr.map(x => resolveOptionLabel(x, cat)).filter(Boolean).join('; ')
        }
      } catch {
        /* fall through */
      }
    }
    return s
  }

  const fa =
    row.final_answer_id ??
    row.finalAnswerId ??
    row.answer_id ??
    row.selected_answer_ids ??
    row.selectedAnswerIds
  if (fa == null) return ''
  if (Array.isArray(fa)) {
    return fa.map(x => resolveOptionLabel(x, cat)).filter(Boolean).join('; ')
  }

  return resolveOptionLabel(fa, cat)
}

/**
 * @param {{ answers?: unknown[], opportunity_id?: string }} answersPayload
 * @param {{ questions?: unknown[] }} questionsPayload
 * @returns {{ opportunity_id: string, rows: { question_id: string, question: string, answer: string }[] }}
 */
export function buildOpportunityExportRows(answersPayload, questionsPayload) {
  const answers = Array.isArray(answersPayload?.answers) ? answersPayload.answers : []
  const catalogByQid = new Map()
  const qList = Array.isArray(questionsPayload)
    ? questionsPayload
    : questionsPayload?.questions || questionsPayload?.data || []
  for (const q of qList) {
    const id = q?.question_id ?? q?.questionId
    if (id != null) catalogByQid.set(String(id), q)
  }

  const rows = answers.map(row => ({
    question_id: String(row.question_id ?? ''),
    question: pickQuestionText(row, catalogByQid),
    answer: pickAnswerDisplay(row, catalogByQid),
  }))

  return {
    opportunity_id: String(answersPayload?.opportunity_id ?? answersPayload?.opportunityId ?? ''),
    rows,
  }
}

export function downloadCsv(exportBundle, filenameBase) {
  const { rows, opportunity_id: oid } = exportBundle
  const header = ['Opportunity ID', 'Question ID', 'Question', 'Answer']
  const lines = [
    header.join(','),
    ...rows.map(r =>
      [
        escapeCsvCell(oid),
        escapeCsvCell(r.question_id),
        escapeCsvCell(r.question),
        escapeCsvCell(r.answer),
      ].join(','),
    ),
  ]
  const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  triggerDownload(blob, `${filenameBase}.csv`)
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** Word / Google Docs–friendly single-file HTML */
export function downloadWordHtmlDoc(exportBundle, title, filenameBase) {
  const { rows, opportunity_id: oid } = exportBundle
  const esc = s =>
    String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  const tableRows = rows
    .map(
      r => `<tr><td>${esc(r.question_id)}</td><td>${esc(r.question)}</td><td>${esc(r.answer)}</td></tr>`,
    )
    .join('')
  const html = `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head><meta charset="utf-8"><title>${esc(title)}</title></head>
<body>
  <h2>${esc(title)}</h2>
  <p><strong>Opportunity ID:</strong> ${esc(oid)}</p>
  <table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;font-family:Calibri,Arial,sans-serif;font-size:11pt;">
    <thead><tr><th>Question ID</th><th>Question</th><th>Answer</th></tr></thead>
    <tbody>${tableRows}</tbody>
  </table>
</body>
</html>`
  const blob = new Blob([html], { type: 'application/msword;charset=utf-8' })
  triggerDownload(blob, `${filenameBase}.doc`)
}

/** Builds a PDF in the browser and triggers download (no print dialog). */
export function downloadExportPdf(exportBundle, title, filenameBase) {
  const { rows, opportunity_id: oid } = exportBundle
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const margin = 14
  const pageW = doc.internal.pageSize.getWidth()
  const maxW = pageW - margin * 2

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.text(title, margin, 18, { maxWidth: maxW })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  doc.text(`Opportunity ID: ${oid}`, margin, 26, { maxWidth: maxW })

  const body = rows.map(r => [
    String(r.question_id ?? ''),
    String(r.question ?? ''),
    String(r.answer ?? ''),
  ])

  autoTable(doc, {
    startY: 32,
    head: [['Question ID', 'Question', 'Answer']],
    body,
    styles: { fontSize: 8, cellPadding: 2, overflow: 'linebreak', valign: 'top' },
    headStyles: { fillColor: [241, 245, 249], textColor: [27, 38, 79], fontStyle: 'bold' },
    columnStyles: {
      0: { cellWidth: 22 },
      1: { cellWidth: 72 },
    },
    margin: { left: margin, right: margin },
    theme: 'grid',
  })

  doc.save(`${filenameBase}.pdf`)
}
