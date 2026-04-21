import { api } from './apiClient'

const SECTION_META = {
  'SaaS Architecture & Technical Fundamentals': {
    id: 'saas-architecture-technical-fundamentals',
    icon: '🏗️',
    color: '#1E40AF',
    bg: 'rgba(30,64,175,.1)',
    subsectionMeta: {
      'Cloud Architecture Concepts':  { icon: '☁️', color: '#2563EB' },
      'Data Security Fundamentals':   { icon: '🔒', color: '#0891B2' },
    },
  },
  'Pricing Packaging & Commercial Terms': {
    id: 'pricing-packaging-commercial-terms',
    icon: '💼',
    color: '#047857',
    bg: 'rgba(5,150,105,.1)',
    subsectionMeta: {
      'SaaS Pricing Models': { icon: '💰', color: '#059669' },
      'Contract Terms':      { icon: '📝', color: '#0D9488' },
    },
  },
  'Integration & Implementation': {
    id: 'integration-implementation',
    icon: '🧩',
    color: '#6D28D9',
    bg: 'rgba(109,40,217,.1)',
    subsectionMeta: {
      'Integration Architecture':        { icon: '🔌', color: '#7C3AED' },
      'Implementation Best Practices':    { icon: '🚀', color: '#9333EA' },
    },
  },
  'Sales Methodology & Process': {
    id: 'sales-methodology-process',
    icon: '🎯',
    color: '#B91C1C',
    bg: 'rgba(185,28,28,.08)',
    subsectionMeta: {
      'Qualification & Discovery': { icon: '🔍', color: '#DC2626' },
      'Objection Handling':        { icon: '🛡️', color: '#EA580C' },
    },
  },
}

const DEFAULT_SECTION_META = {
  icon: '📋', color: '#475569', bg: 'rgba(71,85,105,.08)',
}
const DEFAULT_SUB_META = { icon: '📄', color: '#64748B' }

/**
 * Fetch questions from the API.
 * Response shape: { questions: [{ question_id, question_text, section, subsection }] }
 */
export async function fetchQuestions() {
  const { data } = await api.get('/questions')
  return data.questions
}

/**
 * Convert a flat array of API questions into the section structure
 * used by the app (compatible with allSections / dorSectionData).
 *
 * @param {Array} questions - from the API
 * @param {Object} answersMap - optional { [question_id]: { conf, src, answer } }
 * @returns {Array} section data compatible with allSections entries
 */
export function buildSectionsFromQuestions(questions, answersMap = {}) {
  const grouped = new Map()

  for (const q of questions) {
    const secKey = q.section || 'Uncategorized'
    if (!grouped.has(secKey)) grouped.set(secKey, new Map())

    const subMap = grouped.get(secKey)
    const subKey = q.subsection || 'General'
    if (!subMap.has(subKey)) subMap.set(subKey, [])

    subMap.get(subKey).push(q)
  }

  const sections = []

  for (const [sectionTitle, subMap] of grouped) {
    const meta = SECTION_META[sectionTitle] || {
      ...DEFAULT_SECTION_META,
      id: sectionTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''),
    }

    const qs = []
    const subsectionNames = []

    for (const [subTitle, subQuestions] of subMap) {
      subsectionNames.push(subTitle)
      const subMeta = meta.subsectionMeta?.[subTitle] || DEFAULT_SUB_META

      for (const apiQ of subQuestions) {
        const row = answersMap[apiQ.question_id]
        const conf = row?.conf ?? 0
        const priority = conf >= 60 ? 'P1' : conf >= 40 ? 'P2' : 'P0'

        qs.push({
          id: String(apiQ.question_id || '').replace(/^(qid|dor)-/i, 'QID-') || apiQ.question_id,
          text: apiQ.question_text,
          p: priority,
          pc: priority === 'P1' ? '#D97706' : priority === 'P2' ? '#475569' : '#DC2626',
          answer: row?.answer || 'No extracted answer available for this question.',
          conf,
          status: 'pending',
          override: '',
          srcs: row?.sourceTypes?.length
            ? row.sourceTypes.map(t => {
                const d = { zoom_transcript: { l: 'Zoom', c: '#2D8CFF', t: 'zoom' }, gdrive_doc: { l: 'Google Drive', c: '#34A853', t: 'gdrive' }, slack_messages: { l: 'Slack', c: '#E01E5A', t: 'slack' }, unknown: { l: 'AI Knowledge', c: '#A78BFA', t: 'ai' } }[t] || { l: t, c: '#8B949E', t: 'unknown' }
                return { name: d.l, color: d.c, type: d.t }
              })
            : [],
          subsection: subTitle,
          subsectionColor: subMeta.color,
          subsectionIcon: subMeta.icon,
        })
      }
    }

    sections.push({
      id: meta.id,
      title: sectionTitle,
      icon: meta.icon,
      color: meta.color,
      bg: meta.bg,
      signals: [
        {
          type: 'doc',
          color: '#38BDF8',
          label: sectionTitle,
          text: `<strong>${qs.length}</strong> questions across ${subsectionNames.length} areas: ${subsectionNames.join(', ')}.`,
        },
        { type: 'ai', qs },
      ],
    })
  }

  return sections
}

/**
 * High-level helper: fetch questions from the API and build section data
 * ready to be inserted into allSections for a given opportunity.
 *
 * @param {Object} answersMap - optional answers keyed by question_id
 * @returns {Promise<Array>} section data array
 */
export async function loadQuestionsAsSections(answersMap = {}) {
  const questions = await fetchQuestions()
  return buildSectionsFromQuestions(questions, answersMap)
}
