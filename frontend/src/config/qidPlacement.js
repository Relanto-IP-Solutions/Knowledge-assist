/**
 * Maps QID-001 … QID-042 (and numeric / DOR-NNN variants) to high-level sections and batches.
 * Aligns with qualification rubric: SaaS Architecture → Sales Methodology.
 */

const BATCHES = [
  {
    sectionId: 'saas-architecture-technical-fundamentals',
    sectionTitle: 'SaaS Architecture & Technical Fundamentals',
    subsection: 'Cloud Architecture Concepts',
    start: 1,
    end: 7,
  },
  {
    sectionId: 'saas-architecture-technical-fundamentals',
    sectionTitle: 'SaaS Architecture & Technical Fundamentals',
    subsection: 'Data Security Fundamentals',
    start: 8,
    end: 13,
  },
  {
    sectionId: 'pricing-packaging-commercial-terms',
    sectionTitle: 'Pricing Packaging & Commercial Terms',
    subsection: 'SaaS Pricing Models',
    start: 14,
    end: 18,
  },
  {
    sectionId: 'pricing-packaging-commercial-terms',
    sectionTitle: 'Pricing Packaging & Commercial Terms',
    subsection: 'Contract Terms',
    start: 19,
    end: 23,
  },
  {
    sectionId: 'integration-implementation',
    sectionTitle: 'Integration & Implementation',
    subsection: 'Integration Architecture',
    start: 24,
    end: 28,
  },
  {
    sectionId: 'integration-implementation',
    sectionTitle: 'Integration & Implementation',
    subsection: 'Implementation Best Practices',
    start: 29,
    end: 32,
  },
  {
    sectionId: 'sales-methodology-process',
    sectionTitle: 'Sales Methodology & Process',
    subsection: 'Qualification & Discovery',
    start: 33,
    end: 37,
  },
  {
    sectionId: 'sales-methodology-process',
    sectionTitle: 'Sales Methodology & Process',
    subsection: 'Objection Handling',
    start: 38,
    end: 42,
  },
]

/** Canonical nav + subsection chrome (icons/colors) for QA layout */
export const QA_SECTION_CATALOG = [
  {
    id: 'saas-architecture-technical-fundamentals',
    title: 'SaaS Architecture & Technical Fundamentals',
    icon: '🏗️',
    subsections: [
      { title: 'Cloud Architecture Concepts', icon: '☁️', color: '#2563EB' },
      { title: 'Data Security Fundamentals', icon: '🔒', color: '#0891B2' },
    ],
  },
  {
    id: 'pricing-packaging-commercial-terms',
    title: 'Pricing Packaging & Commercial Terms',
    icon: '💼',
    subsections: [
      { title: 'SaaS Pricing Models', icon: '💰', color: '#059669' },
      { title: 'Contract Terms', icon: '📝', color: '#0D9488' },
    ],
  },
  {
    id: 'integration-implementation',
    title: 'Integration & Implementation',
    icon: '🧩',
    subsections: [
      { title: 'Integration Architecture', icon: '🔌', color: '#7C3AED' },
      { title: 'Implementation Best Practices', icon: '🚀', color: '#9333EA' },
    ],
  },
  {
    id: 'sales-methodology-process',
    title: 'Sales Methodology & Process',
    icon: '🎯',
    subsections: [
      { title: 'Qualification & Discovery', icon: '🔍', color: '#DC2626' },
      { title: 'Objection Handling', icon: '🛡️', color: '#EA580C' },
    ],
  },
]

const SUBSTYLE = new Map()
for (const sec of QA_SECTION_CATALOG) {
  for (const sub of sec.subsections) {
    SUBSTYLE.set(sub.title, { icon: sub.icon, color: sub.color })
  }
}

export function parseQidSerial(questionId) {
  if (questionId == null || questionId === '') return null
  const s = String(questionId).trim().toUpperCase()
  let m = s.match(/^QID-(\d+)$/)
  if (m) return parseInt(m[1], 10)
  m = s.match(/^DOR-(\d+)$/)
  if (m) return parseInt(m[1], 10)
  m = s.match(/^(\d+)$/)
  if (m) return parseInt(m[1], 10)
  m = s.match(/(\d+)\s*$/)
  if (m) return parseInt(m[1], 10)
  return null
}

/**
 * @returns {{ sectionId: string, sectionTitle: string, subsection: string } | null}
 */
export function placementForQuestionId(questionId) {
  const n = parseQidSerial(questionId)
  if (n == null || n < 1 || n > 42) return null
  for (const b of BATCHES) {
    if (n >= b.start && n <= b.end) {
      return {
        sectionId: b.sectionId,
        sectionTitle: b.sectionTitle,
        subsection: b.subsection,
      }
    }
  }
  return null
}

export function subsectionChrome(subsectionTitle) {
  return SUBSTYLE.get(subsectionTitle) || { icon: '📄', color: '#64748B' }
}

/**
 * Group API answer rows by section → subsection order from catalog.
 * @param {Array<{ question_id: string }>} answers
 */
export function groupAnswersByQaCatalog(answers) {
  const sections = QA_SECTION_CATALOG.map(def => ({
    id: def.id,
    title: def.title,
    icon: def.icon,
    subsections: def.subsections.map(sub => ({
      title: sub.title,
      icon: sub.icon,
      color: sub.color,
      answers: [],
    })),
  }))
  const sectionById = new Map(sections.map(s => [s.id, s]))
  const uncategorized = []

  for (const a of answers || []) {
    const p = placementForQuestionId(a.question_id)
    if (!p) {
      uncategorized.push(a)
      continue
    }
    const sec = sectionById.get(p.sectionId)
    if (!sec) {
      uncategorized.push(a)
      continue
    }
    const sub = sec.subsections.find(x => x.title === p.subsection)
    if (sub) sub.answers.push(a)
    else uncategorized.push(a)
  }

  return { sections, uncategorized }
}

/**
 * Question ids belonging to one nav section (or `uncategorized`) for section-scoped POST /answers.
 * @param {{ sections: Array<{ id: string, subsections: Array<{ answers: unknown[] }> }>, uncategorized: Array<{ question_id?: string }> } | null | undefined} grouped
 * @param {string} sectionId - catalog section id or `'uncategorized'`
 * @returns {Set<string>}
 */
export function getQuestionIdsForQaSection(grouped, sectionId) {
  const ids = new Set()
  if (!grouped || sectionId == null || sectionId === '') return ids
  if (sectionId === 'uncategorized') {
    for (const a of grouped.uncategorized || []) {
      if (a?.question_id != null) ids.add(String(a.question_id))
    }
    return ids
  }
  const sec = grouped.sections?.find(s => s.id === sectionId)
  if (!sec) return ids
  for (const sub of sec.subsections || []) {
    for (const a of sub.answers || []) {
      if (a?.question_id != null) ids.add(String(a.question_id))
    }
  }
  return ids
}

/**
 * Same grouping as {@link groupAnswersByQaCatalog} for review question payloads.
 * @param {Array<{ question_id: string }>} questions
 */
export function groupReviewQuestionsByQaCatalog(questions) {
  const sections = QA_SECTION_CATALOG.map(def => ({
    id: def.id,
    title: def.title,
    icon: def.icon,
    subsections: def.subsections.map(sub => ({
      title: sub.title,
      icon: sub.icon,
      color: sub.color,
      questions: [],
    })),
  }))
  const sectionById = new Map(sections.map(s => [s.id, s]))
  const uncategorized = []

  for (const q of questions || []) {
    const p = placementForQuestionId(q.question_id)
    if (!p) {
      uncategorized.push(q)
      continue
    }
    const sec = sectionById.get(p.sectionId)
    if (!sec) {
      uncategorized.push(q)
      continue
    }
    const sub = sec.subsections.find(x => x.title === p.subsection)
    if (sub) sub.questions.push(q)
    else uncategorized.push(q)
  }

  return { sections, uncategorized }
}
