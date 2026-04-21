/**
 * Enrich a raw answers export (e.g. oid0009_responses_form_output_*.json) with
 * answer_id on each row and conflicts[], selected_answer_ids for multi-select arrays,
 * and conflict_id when conflicts exist.
 *
 * Usage: node scripts/enrich-answers-export.mjs path/to/input.json
 * Writes path/to/input_with_answer_ids.json next to the input (same directory).
 */

import fs from 'node:fs'
import path from 'node:path'
import { enrichAnswersResponsePayload } from '../src/utils/enrichAnswerIds.js'

const inPath = process.argv[2]
if (!inPath) {
  console.error('Usage: node scripts/enrich-answers-export.mjs <input.json>')
  process.exit(1)
}

const abs = path.isAbsolute(inPath) ? inPath : path.join(process.cwd(), inPath)
const raw = JSON.parse(fs.readFileSync(abs, 'utf8'))
const out = enrichAnswersResponsePayload(raw)
const dir = path.dirname(abs)
const base = path.basename(abs, '.json')
const dest = path.join(dir, `${base}_with_answer_ids.json`)
fs.writeFileSync(dest, `${JSON.stringify(out, null, 2)}\n`, 'utf8')
console.log('Wrote', dest)
