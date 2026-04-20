export const opps = [
  {
    id: 'oid0009', name: 'NovaPulse', value: '$2.8M', board: 'ent',
    owner: 'Sarah Chen', closeDate: 'Mar 31', stage: 'Discovery', days: 18,
    ai: 10, human: 12, total: 22, max: 42, status: 'review',
    badge: 'hot', badgeTxt: '● COMMIT', score: 74, dotColor: '#E3B341',
    action: 'Updated AI recommendation for 12 Questions',
    warnings: [
      { type: 'Champion Change',      icon: '👤', color: '#FF7B72' },
      { type: 'No Decision Maker',    icon: '🚫', color: '#FF7B72' },
      { type: 'Pricing Not Mentioned',icon: '💬', color: '#E3B341' },
    ],
    todos: [
      { text: 'Schedule briefing call with Priya Mehta (new champion)', priority: 'P0', done: false },
      { text: 'Engage CFO David Park before Feb budget review',          priority: 'P0', done: false },
      { text: 'Send competitive one-pager to Ravi Verma',               priority: 'P1', done: true  },
    ],
    contacts: [
      { name: 'Priya Mehta', title: 'CTO',    initials: 'PM', color: '#8B5CF6', acts: [0,2,0,3,1,0,2,0,0,1,3,2,0,0,1,0,2,3,0,1,0] },
      { name: 'Ravi Verma',  title: 'VP Eng', initials: 'RV', color: '#38BDF8', acts: [1,0,2,0,1,1,0,2,0,0,1,0,1,0,2,1,0,0,1,0,1] },
      { name: 'David Park',  title: 'CFO',    initials: 'DP', color: '#F85149', acts: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0] },
    ],
  },
  {
    id: 'OID/112299', name: 'Veltrix', value: '$980K', board: 'smb',
    owner: "James O'Brien", closeDate: 'Apr 15', stage: 'Follow-up', days: 34,
    ai: 22, human: 0, total: 22, max: 42, status: 'review',
    badge: 'hot', badgeTxt: '● REVIEW', score: 48, dotColor: '#A78BFA',
    action: '22 AI answers extracted — manual review needed',
    warnings: [{ type: 'Single-Threaded', icon: '🧵', color: '#E3B341' }],
    todos: [
      { text: 'Complete AI signal extraction — 5 min remaining',    priority: 'P0', done: false },
      { text: 'Schedule follow-up call to define POC scope',         priority: 'P1', done: false },
    ],
    contacts: [
      { name: "James O'Brien", title: 'AE',    initials: 'JO', color: '#56D364', acts: [1,1,0,1,0,0,1,0,1,0,1,1,0,0,0,1,0,1,0,0,1] },
      { name: 'Mike Torres',   title: 'VP IT', initials: 'MT', color: '#38BDF8', acts: [0,1,0,0,1,0,0,0,1,0,0,1,0,0,0,0,0,1,0,0,0] },
    ],
  },
  {
    id: 'OID/99132112', name: 'Apexora Systems', value: '$1.3M', board: 'ent',
    owner: 'Sarah Chen', closeDate: 'Feb 28', stage: 'Proposal', days: 52,
    ai: 60, human: 20, total: 80, max: 120, status: 'review',
    badge: 'risk', badgeTxt: '⚠ AT RISK', score: 31, dotColor: '#FF7B72',
    action: 'Just 5 more questions to complete',
    warnings: [
      { type: 'No Prospect Activity', icon: '📭', color: '#FF7B72' },
      { type: 'Champion Change',      icon: '👤', color: '#FF7B72' },
    ],
    todos: [
      { text: 'Identify new champion — previous contact unresponsive', priority: 'P0', done: false },
      { text: 'Unblock budget stall — reach out to CFO directly',      priority: 'P0', done: false },
    ],
    contacts: [
      { name: 'Alex Turner', title: 'Dir. Strategy', initials: 'AT', color: '#FF7B72', acts: [0,1,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0] },
      { name: 'Lena Cruz',   title: 'CFO',           initials: 'LC', color: '#E3B341', acts: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0] },
    ],
  },
  {
    id: 'OID/343356', name: 'Bluefin Labs', value: '$450K', board: 'smb',
    owner: 'Marcus Liu', closeDate: 'May 30', stage: 'Discovery', days: 71,
    ai: 60, human: 20, total: 80, max: 120, status: 'progress',
    badge: 'cold', badgeTxt: '⏸ STALLED', score: 22, dotColor: '#79C0FF',
    action: '12 min to complete AI Extraction',
    warnings: [
      { type: 'No Activity (14d)', icon: '🔇', color: '#FF7B72' },
      { type: 'Single-Threaded',   icon: '🧵', color: '#E3B341' },
    ],
    todos: [
      { text: 'Re-engage prospect — no activity in 14 days',       priority: 'P0', done: false },
      { text: 'Expand stakeholder map — currently single-threaded', priority: 'P1', done: false },
    ],
    contacts: [
      { name: 'Dana Hill', title: 'Head of Ops', initials: 'DH', color: '#79C0FF', acts: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0] },
    ],
  },
  {
    id: 'OID/553211', name: 'Crestwave Tech', value: '$2.1M', board: 'ent',
    owner: 'Priya Nair', closeDate: 'Mar 15', stage: 'Negotiation', days: 12,
    ai: 90, human: 30, total: 100, max: 120, status: 'review',
    badge: 'strong', badgeTxt: '● BEST CASE', score: 82, dotColor: '#56D364',
    action: 'Ready for final review',
    warnings: [],
    todos: [
      { text: 'Legal to review final contract draft',          priority: 'P0', done: false },
      { text: 'Get exec sign-off before Mar 15 close date',   priority: 'P0', done: false },
      { text: 'Confirm implementation kickoff timeline',      priority: 'P1', done: true  },
    ],
    contacts: [
      { name: 'Chris Wade',  title: 'VP Operations', initials: 'CW', color: '#38BDF8', acts: [1,2,1,3,1,2,1,2,1,2,1,3,1,2,1,2,1,2,3,2,1] },
      { name: 'Priya Nair',  title: 'AE (Owner)',    initials: 'PN', color: '#56D364', acts: [2,3,2,3,2,1,3,2,2,3,2,3,2,2,3,2,2,3,2,3,2] },
      { name: 'Rachel Obi',  title: 'Procurement',   initials: 'RO', color: '#E3B341', acts: [0,1,2,1,0,1,2,0,1,2,1,0,2,1,0,1,2,1,0,2,1] },
    ],
  },
  {
    id: 'OID/771002', name: 'Northstar Analytics', value: '$720K', board: 'smb',
    owner: "James O'Brien", closeDate: 'Apr 30', stage: 'Discovery', days: 8,
    ai: 55, human: 25, total: 70, max: 120, status: 'review',
    badge: 'warm', badgeTxt: '~ UPSIDE', score: 61, dotColor: '#F8814A',
    action: 'Needs 2 more source documents',
    warnings: [{ type: 'Pricing Not Mentioned', icon: '💬', color: '#E3B341' }],
    todos: [
      { text: 'Upload 2 remaining source documents',                   priority: 'P0', done: false },
      { text: 'Schedule pricing discussion — not yet raised in calls', priority: 'P1', done: false },
    ],
    contacts: [
      { name: "James O'Brien", title: 'AE',             initials: 'JO', color: '#F8814A', acts: [0,1,0,1,1,0,0,1,0,0,1,0,1,0,0,1,0,1,0,0,1] },
      { name: 'Sophie Tan',    title: 'Dir. Innovation', initials: 'ST', color: '#A78BFA', acts: [1,0,1,0,0,1,0,1,1,0,0,1,0,0,1,0,1,0,0,1,0] },
    ],
  },
]

export const badgeStyles = {
  hot:       { bg: 'rgba(210,153,34,.12)', color: '#E3B341', border: 'rgba(210,153,34,.3)' },
  warm:      { bg: 'rgba(248,129,74,.1)',  color: '#F8814A', border: 'rgba(248,129,74,.25)' },
  cold:      { bg: 'rgba(56,189,248,.08)', color: '#79C0FF', border: 'rgba(56,189,248,.2)' },
  risk:      { bg: 'rgba(248,81,73,.1)',   color: '#FF7B72', border: 'rgba(248,81,73,.3)' },
  strong:    { bg: 'rgba(63,185,80,.1)',   color: '#56D364', border: 'rgba(63,185,80,.3)' },
  progress:  { bg: 'rgba(139,92,246,.1)', color: '#A78BFA', border: 'rgba(139,92,246,.3)' },
  accepted:  { bg: 'rgba(63,185,80,.1)',   color: '#56D364', border: 'rgba(63,185,80,.3)' },
  overridden:{ bg: 'rgba(210,153,34,.1)', color: '#E3B341', border: 'rgba(210,153,34,.3)' },
  pending:   { bg: 'rgba(255,255,255,.04)',color: '#8B949E', border: '#30363D' },
  p0:        { bg: 'rgba(248,81,73,.1)',   color: '#FF7B72', border: 'rgba(248,81,73,.3)' },
  p1:        { bg: 'rgba(210,153,34,.1)',  color: '#E3B341', border: 'rgba(210,153,34,.3)' },
  p2:        { bg: 'rgba(255,255,255,.04)',color: '#484F58', border: '#30363D' },
}

const dorAnswersByQid = {
  'DOR-001': { conf: 49, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Multi-tenant SaaS architecture uses shared infrastructure with logical data isolation (tenant-scoped queries and row-level controls). Single-tenant provides physically separate infrastructure.' },
  'DOR-003': { conf: 49, src: 'NovaPulse_Call_01_Discovery_ProductFeatures.txt', answer: 'The payload highlights API importance for integration/custom internal tooling and for data portability (export in formats such as CSV/JSON/Parquet).' },
  'DOR-004': { conf: 49, src: 'NovaPulse_Call_01_Discovery_ProductFeatures.txt', answer: 'REST follows OpenAPI 3.0. GraphQL supports nested queries and real-time subscription style access.' },
  'DOR-006': { conf: 49, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'SLA review focus: uptime guarantees, P1 response times, escalation model, and breach remedies/credit tiers including remedy scope.' },
  'DOR-008': { conf: 49, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Encryption at rest, key ownership/rotation policy, and optional BYOK/field-level controls are the key controls called out for enterprise validation.' },
  'DOR-009': { conf: 47, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'SOC 2 Type I validates control design at a point in time; Type II validates operational effectiveness over a multi-month period.' },
  'DOR-010': { conf: 50, src: 'NovaPulse_Call_01_Discovery_ProductFeatures.txt', answer: 'MFA is positioned as mandatory for business SaaS risk posture, with support across TOTP, hardware keys, and push flows.' },
  'DOR-011': { conf: 47, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'RBAC simplifies policy management but can become rigid at scale; ABAC enables finer attribute-based controls (department/region/etc.).' },
  'DOR-012': { conf: 47, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Pen testing expectations include independent firm credentials, cadence, scope, report sharing under NDA, and remediation process transparency.' },
  'DOR-013': { conf: 50, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Post-termination handling includes a 30-day export window and staged deletion windows with deletion confirmation support.' },
  'DOR-014': { conf: 49, src: 'NovaPulse_Call_02_Pricing_Competitive_ROI.txt', answer: 'Pricing model references include per-user billing with annual vs monthly options, onboarding/setup scope, and add-on scoped services.' },
  'DOR-015': { conf: 49, src: 'NovaPulse_Call_02_Pricing_Competitive_ROI.txt', answer: 'Free trial and PoC constraints include duration, user/storage limits, feature scope, and supported success criteria for formal evaluation.' },
  'DOR-016': { conf: 36, src: 'NovaPulse_Product_Reference.txt', answer: 'TCO framing extends beyond license line-item cost into labor, maintenance burden, and opportunity-cost impact.' },
  'DOR-017': { conf: 49, src: 'NovaPulse_Call_02_Pricing_Competitive_ROI.txt', answer: 'Annual billing generally improves unit economics while monthly billing increases flexibility; decision is driven by commitment confidence.' },
  'DOR-018': { conf: 36, src: 'NovaPulse_Call_02_Pricing_Competitive_ROI.txt', answer: 'Three-year cost inventory should include subscription, onboarding/integration, operational labor, feature add-ons, and contract/renewal terms.' },
  'DOR-019': { conf: 49, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'MSA baseline covers legal/commercial relationship terms such as indemnity, liability, DPA/privacy, and portability/termination guardrails.' },
  'DOR-020': { conf: 49, src: 'NovaPulse_Product_Reference.txt', answer: 'Vendor lock-in mitigation is contract-first: data ownership, open export formats, and explicit portability rights.' },
  'DOR-021': { conf: 48, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Indemnification allocates legal risk; IP indemnity is especially critical so customer exposure is not shifted by default vendor terms.' },
  'DOR-022': { conf: 48, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Breach notification terms should define timing (for example 72 hours), scope of disclosure, and a responsible incident liaison.' },
  'DOR-023': { conf: 35, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'Most negotiated MSA clauses in payload context: indemnity, liability caps, DPA terms, portability/deletion, and SLA remedy language.' },
  'DOR-025': { conf: 48, src: 'NovaPulse_Call_03_TechnicalDeepDive_Security_Legal.txt', answer: 'SCIM 2.0 is highlighted for automated provisioning/de-provisioning through enterprise identity providers.' },
  'DOR-026': { conf: 35, src: 'NovaPulse_Call_01_Discovery_ProductFeatures.txt', answer: 'Webhooks are event-driven pushes; polling repeatedly checks state. Payload explains webhook model as lower-latency and lower-chatter.' },
  'DOR-028': { conf: 49, src: 'NovaPulse_Call_01_Discovery_ProductFeatures.txt', answer: 'Architecture recommendation favors unified platform + single data model over point-to-point integration sprawl.' },
  'DOR-029': { conf: 47, src: 'NovaPulse_Product_Reference_2.txt', answer: 'PoC value is defined as structured, criteria-driven validation with real use cases, not a feature-only vendor demo.' },
  'DOR-030': { conf: 47, src: 'NovaPulse_Product_Reference.txt', answer: 'Change management is treated as adoption-critical: communication/training/support plans reduce resistance and increase realized value.' },
  'DOR-034': { conf: 36, src: 'NovaPulse_Product_Reference.txt', answer: 'SQL vs MQL qualification is represented by budget confirmation, user scope, economic buyer access, and go-live horizon criteria.' },
  'DOR-036': { conf: 36, src: 'NovaPulse_Product_Reference.txt', answer: 'Multi-threading is framed as a major lever for improving close rates and shortening cycle time in enterprise deals.' },
  'DOR-039': { conf: 49, src: 'NovaPulse_Product_Reference_1.txt', answer: 'Cost-of-delay reframes budget timing objections by quantifying status-quo loss vs projected time-to-ROI.' },
}

const SOURCE_TYPE_DISPLAY = {
  zoom_transcript:  { label: 'Zoom',         color: '#2D8CFF', type: 'zoom' },
  gdrive_doc:       { label: 'Google Drive',  color: '#34A853', type: 'gdrive' },
  slack_messages:   { label: 'Slack',         color: '#E01E5A', type: 'slack' },
  unknown:          { label: 'AI Knowledge',  color: '#A78BFA', type: 'ai' },
}

const sourceTypesByQid = {
  'DOR-001': ['zoom_transcript'],
  'DOR-003': ['zoom_transcript'],
  'DOR-004': ['zoom_transcript'],
  'DOR-006': ['zoom_transcript'],
  'DOR-008': ['zoom_transcript'],
  'DOR-009': ['zoom_transcript'],
  'DOR-010': ['zoom_transcript'],
  'DOR-011': ['zoom_transcript'],
  'DOR-012': ['zoom_transcript'],
  'DOR-013': ['zoom_transcript'],
  'DOR-014': ['zoom_transcript'],
  'DOR-015': ['zoom_transcript'],
  'DOR-016': ['gdrive_doc', 'zoom_transcript'],
  'DOR-017': ['zoom_transcript'],
  'DOR-018': ['gdrive_doc', 'zoom_transcript'],
  'DOR-019': ['zoom_transcript'],
  'DOR-020': ['gdrive_doc'],
  'DOR-021': ['zoom_transcript'],
  'DOR-022': ['zoom_transcript'],
  'DOR-023': ['gdrive_doc', 'zoom_transcript'],
  'DOR-025': ['zoom_transcript'],
  'DOR-026': ['slack_messages', 'zoom_transcript'],
  'DOR-028': ['zoom_transcript'],
  'DOR-029': ['gdrive_doc'],
  'DOR-030': ['gdrive_doc'],
  'DOR-034': ['gdrive_doc'],
  'DOR-036': ['gdrive_doc'],
  'DOR-039': ['gdrive_doc'],
}

const sourceTypesByQidVeltrix = {
  'DOR-001': ['unknown'], 'DOR-002': ['unknown'], 'DOR-003': ['unknown'],
  'DOR-004': ['unknown'], 'DOR-005': ['unknown'], 'DOR-006': ['unknown'],
  'DOR-007': ['unknown'], 'DOR-008': ['unknown'], 'DOR-009': ['unknown'],
  'DOR-010': ['unknown'], 'DOR-011': ['unknown'], 'DOR-012': ['unknown'],
  'DOR-013': ['unknown'],
  'DOR-038': ['unknown'], 'DOR-039': ['unknown'], 'DOR-040': ['unknown'],
  'DOR-041': ['unknown'], 'DOR-042': ['unknown'],
}

const dorAnswersByQidVeltrix = {
  'DOR-001': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Multi-tenant shares infrastructure with logical data isolation per tenant; single-tenant provides dedicated instances per customer with greater customisation but higher cost.' },
  'DOR-002': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Cloud-native leverages containers, microservices, and orchestration (Kubernetes) for scalability, resilience, and faster feature delivery in cloud environments.' },
  'DOR-003': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'APIs enable seamless integration with existing systems (CRM, ERP), automate workflows, and facilitate data synchronisation when adopting a new SaaS platform.' },
  'DOR-004': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'REST uses standard HTTP methods for resource-oriented access with caching; GraphQL allows clients to request exactly the data they need in a single flexible query.' },
  'DOR-005': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Microservices decompose applications into independent services, improving reliability, enabling faster feature delivery, and allowing independent scaling per service.' },
  'DOR-006': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'SLA defines expected service levels. Key elements: uptime guarantees, performance metrics, support response times, backup/recovery, security commitments, and penalty/credit terms.' },
  'DOR-007': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Assess 99.99% uptime via architectural redundancy review, SRE practices, historical performance data, third-party certifications (SOC 2, ISO 27001), and DR drills with defined RTO/RPO.' },
  'DOR-008': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Encryption at rest protects stored data from unauthorised access even if storage infrastructure is compromised. Essential for compliance and data confidentiality.' },
  'DOR-009': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'SOC 2 Type I validates control design at a point in time; Type II validates operational effectiveness over 6\u201312 months, providing stronger assurance.' },
  'DOR-010': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'MFA requires multiple verification factors (knowledge, possession, biometric), significantly reducing unauthorised access risk even if passwords are compromised.' },
  'DOR-011': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'RBAC assigns permissions via roles for simplicity; ABAC uses user/resource/environment attributes for finer-grained, context-aware access control. RBAC can become rigid at scale.' },
  'DOR-012': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Penetration tests simulate cyberattacks to find exploitable vulnerabilities. Ask about frequency, scope, methodology, third-party testers, report sharing, and remediation process.' },
  'DOR-013': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Acquisition: contractual obligations transfer with notification and data export options. Insolvency: ample notice period, data export window, then secure deletion per retention policy.' },
  'DOR-033': { conf: 0, src: 'AI Knowledge · direct answer', answer: 'BANT stands for Budget, Authority, Need, Timeline \u2014 a framework to qualify whether a prospect has the capacity and intent to purchase.' },
  'DOR-034': { conf: 0, src: 'AI Knowledge · direct answer', answer: 'MQLs are marketing-engaged prospects meeting lead criteria; SQLs are sales-vetted prospects with defined need, budget, authority, and timeline ready for direct engagement.' },
  'DOR-035': { conf: 0, src: 'AI Knowledge · direct answer', answer: 'MEDDIC (Metrics, Economic Buyer, Decision Criteria/Process, Implicate Pain, Champion) provides deeper strategic qualification than BANT for complex enterprise sales.' },
  'DOR-036': { conf: 0, src: 'AI Knowledge · direct answer', answer: 'Multi-threading engages multiple stakeholders across departments to reduce single-point-of-failure risk and build broader internal consensus for the deal.' },
  'DOR-037': { conf: 0, src: 'AI Knowledge · direct answer', answer: 'Stalled deals likely face internal bureaucracy, competing priorities, hidden objections, or lack of urgency. Diagnose by mapping internal process and re-engaging economic buyer.' },
  'DOR-038': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'LAER-C framework: Listen actively, Acknowledge concern, Explore root cause with clarifying questions, Respond with evidence, Confirm resolution with the prospect.' },
  'DOR-039': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Cost-of-delay quantifies the financial impact of inaction \u2014 lost revenue, increased costs, compliance risks \u2014 to reframe budget timing objections around status-quo loss.' },
  'DOR-040': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Feature objections target specific capabilities (address with workarounds/roadmap); fit objections question overall alignment (address by revisiting strategic goals and demonstrating value).' },
  'DOR-041': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Acknowledge similarity, shift focus to their unique needs, highlight differentiated outcomes and customer success stories, then propose a tailored deeper evaluation.' },
  'DOR-042': { conf: 0, src: 'AI Knowledge · conflict resolution', answer: 'Acknowledge the analysis, verify apples-to-apples comparison, reframe to TCO/ROI and unique value differentiation, explore scope adjustments only as last resort.' },
}

const dorSections = [
  {
    id: 'saas-architecture-technical-fundamentals',
    title: 'SaaS Architecture & Technical Fundamentals',
    icon: '🏗️',
    color: '#1E40AF',
    bg: 'rgba(30,64,175,.1)',
    subsections: [
      { title: 'Cloud Architecture Concepts', count: 7, icon: '☁️', color: '#2563EB' },
      { title: 'Data Security Fundamentals', count: 6, icon: '🔒', color: '#0891B2' },
    ],
  },
  {
    id: 'pricing-packaging-commercial-terms',
    title: 'Pricing Packaging & Commercial Terms',
    icon: '💼',
    color: '#047857',
    bg: 'rgba(5,150,105,.1)',
    subsections: [
      { title: 'SaaS Pricing Models', count: 5, icon: '💰', color: '#059669' },
      { title: 'Contract Terms', count: 5, icon: '📝', color: '#0D9488' },
    ],
  },
  {
    id: 'integration-implementation',
    title: 'Integration & Implementation',
    icon: '🧩',
    color: '#6D28D9',
    bg: 'rgba(109,40,217,.1)',
    subsections: [
      { title: 'Integration Architecture', count: 5, icon: '🔌', color: '#7C3AED' },
      { title: 'Implementation Best Practices', count: 4, icon: '🚀', color: '#9333EA' },
    ],
  },
  {
    id: 'sales-methodology-process',
    title: 'Sales Methodology & Process',
    icon: '🎯',
    color: '#B91C1C',
    bg: 'rgba(185,28,28,.08)',
    subsections: [
      { title: 'Qualification & Discovery', count: 5, icon: '🔍', color: '#DC2626' },
      { title: 'Objection Handling', count: 5, icon: '🛡️', color: '#EA580C' },
    ],
  },
]

const dorQuestionTextByQid = {
  'DOR-001': 'What is the difference between multi-tenant and single-tenant SaaS architecture?',
  'DOR-002': 'What does "cloud-native" mean and why does it matter when evaluating a SaaS product?',
  'DOR-003': 'What is an API and why is it important when a business adopts a new SaaS platform?',
  'DOR-004': 'What is the difference between REST and GraphQL APIs and when would a customer prefer each?',
  'DOR-005': "What is a microservices architecture and what are its main advantages for a SaaS vendor's customers?",
  'DOR-006': 'What is an SLA (Service Level Agreement) and what are the most important elements a customer should look for in one?',
  'DOR-007': "A prospect's CTO asks: We need 99.99% uptime. How do I assess whether any SaaS vendor can actually deliver this? Walk through a rigorous vendor uptime assessment framework.",
  'DOR-008': 'What does "encryption at rest" mean and why should customers ask about it when evaluating a SaaS vendor?',
  'DOR-009': 'What is the difference between SOC 2 Type I and SOC 2 Type II certification?',
  'DOR-010': 'What is MFA (Multi-Factor Authentication) and why should it be mandatory for SaaS platforms used in business?',
  'DOR-011': 'What is RBAC (Role-Based Access Control) and what are its limitations compared to ABAC (Attribute-Based Access Control)?',
  'DOR-012': 'What is a penetration test and what questions should a customer ask a vendor about their penetration testing practices?',
  'DOR-013': 'A CISO asks: Walk me through what actually happens to our data if your company is acquired by a competitor or goes out of business. Construct a comprehensive answer.',
  'DOR-014': 'What are the most common SaaS pricing models and what are the advantages of each?',
  'DOR-015': 'What is a free trial in SaaS and what are the most important limitations customers should look for?',
  'DOR-016': 'What is total cost of ownership (TCO) in the context of a SaaS purchase and why is it more meaningful than licence cost comparison?',
  'DOR-017': 'What is the difference between annual and monthly SaaS billing and when should a customer choose each?',
  'DOR-018': 'A CFO asks: Before I approve this SaaS purchase, walk me through every cost that will appear on our P&L over the next three years. Construct a complete cost inventory framework.',
  'DOR-019': 'What is an MSA (Master Service Agreement) and what does it typically cover in a SaaS context?',
  'DOR-020': 'What is vendor lock-in and how can a customer protect against it contractually?',
  'DOR-021': 'What is an indemnification clause in a SaaS contract and why does it matter?',
  'DOR-022': 'What is a data breach notification clause and what response time should customers require?',
  'DOR-023': "A legal team presents a vendor's standard MSA and asks you to identify the five most important clauses to negotiate before signing. What are they and why?",
  'DOR-024': 'What is an iPaaS (Integration Platform as a Service) and when should a customer use one instead of native integrations?',
  'DOR-025': 'What is SCIM (System for Cross-domain Identity Management) and why is it important for enterprise software purchases?',
  'DOR-026': 'What is a webhook and how does it differ from polling-based API integration?',
  'DOR-027': 'A customer asks: What is the best way to plan an integration between a new SaaS platform and our existing CRM? Walk through a structured integration planning approach.',
  'DOR-028': 'An IT Director says: We run 14 different SaaS tools and every integration is its own custom project. What is the right architectural answer to this problem? Construct a strategic response.',
  'DOR-029': 'What is a Proof of Concept (PoC) in a SaaS evaluation and why is it more valuable than a vendor demo?',
  'DOR-030': 'What is change management in a software implementation and why is it critical for user adoption?',
  'DOR-031': 'What is a parallel run in a software implementation and when is it used?',
  'DOR-032': 'What are the most common reasons enterprise SaaS implementations run over time or over budget?',
  'DOR-033': 'What is BANT qualification and what does each letter stand for?',
  'DOR-034': 'What is the difference between a Marketing Qualified Lead (MQL) and a Sales Qualified Lead (SQL)?',
  'DOR-035': 'What is MEDDIC and how does it improve on BANT for complex enterprise sales?',
  'DOR-036': 'What is multi-threading in enterprise sales and why does it improve close rates?',
  'DOR-037': 'A sales representative has been working a deal for six weeks. The champion is enthusiastic, the PoC went well, and the economic buyer verbally agreed but nothing has been signed. What are the most likely scenarios and how should the sales representative diagnose and address each?',
  'DOR-038': 'What is the most effective structure for handling a sales objection?',
  'DOR-039': 'What is the "cost of delay" framework for the "we don\'t have budget right now" objection?',
  'DOR-040': 'What is the difference between a feature objection and a fit objection and how should each be handled differently?',
  'DOR-041': "How should a sales representative respond when a prospect says we're talking to three other vendors and you all look the same to us?",
  'DOR-042': "A well-prepared prospect CFO presents a spreadsheet showing your platform costs 22% more per user than a competitor over three years. They ask you to match the competitor's price. Walk through the complete response framework.",
}

const conflictsByQid = {
  'DOR-001': [
    { answer: 'Multi-tenant SaaS architecture involves multiple customers (tenants) sharing the same underlying infrastructure, with logical data isolation enforced at the application and database layers (e.g., tenant ID-scoped queries, row-level security). In contrast, single-tenant SaaS architecture provides dedicated infrastructure per customer.', conf: 49, srcType: 'zoom_transcript' },
    { answer: 'Multi-tenant SaaS architecture means multiple customers (tenants) share the same underlying infrastructure and application instance, with logical data isolation at the application and database layers. Single-tenant dedicated cloud architecture provides physically separate infrastructure for each customer.', conf: 49, srcType: 'zoom_transcript' },
  ],
  'DOR-008': [
    { answer: 'Encryption at rest refers to encrypting data when it is stored on a physical medium, such as a database, file system, or storage device. This protects data from unauthorized access if the storage medium is compromised. Customers should ask about it to ensure their sensitive data is protected.', conf: 49, srcType: 'zoom_transcript' },
    { answer: 'Encryption at rest refers to encrypting data when it is stored on a disk or in a database, rather than when it is being transmitted. The purpose is to protect data from unauthorized access if the storage medium is compromised.', conf: 47, srcType: 'zoom_transcript' },
  ],
  'DOR-009': [
    { answer: 'SOC 2 Type I certification is a point-in-time assessment that confirms a vendor\'s controls were appropriately designed at the audit date. SOC 2 Type II covers an extended period (6\u201312 months) and confirms those controls were operating effectively.', conf: 47, srcType: 'zoom_transcript' },
    { answer: 'SOC 2 Type I is a report on the design of a service organization\'s controls at a specific point in time. SOC 2 Type II covers an extended period (6\u201312 months) and confirms that those controls were operating effectively.', conf: 47, srcType: 'zoom_transcript' },
  ],
  'DOR-010': [
    { answer: 'MFA is a security system requiring two or more verification factors: something you know (password), something you have (phone/hardware key), and something you are (biometric). It significantly reduces unauthorized access risk.', conf: 50, srcType: 'zoom_transcript' },
    { answer: 'MFA requires users to provide two or more verification factors (knowledge, possession, biometric) to gain access. These factors work together so that even if one is compromised, unauthorized access is still prevented.', conf: 50, srcType: 'zoom_transcript' },
  ],
  'DOR-011': [
    { answer: 'RBAC assigns permissions to roles and users to roles. It simplifies access management by grouping users (e.g., Admin, Editor, Viewer). Its limitation is that it can become rigid at scale when fine-grained attribute-based decisions are needed.', conf: 47, srcType: 'zoom_transcript' },
    { answer: 'RBAC associates permissions with roles, and users are assigned to those roles. Its primary limitation is that it becomes inflexible at scale. ABAC uses user/resource/environment attributes for finer-grained, context-aware access control.', conf: 47, srcType: 'zoom_transcript' },
  ],
  'DOR-012': [
    { answer: 'A penetration test is a simulated cyberattack to check for exploitable vulnerabilities. Customers should ask about frequency, scope, methodology, whether independent third-party testers are used, report sharing under NDA, and remediation process.', conf: 47, srcType: 'zoom_transcript' },
    { answer: 'A penetration test simulates cyberattacks to identify weaknesses in security defenses. Key questions for vendors: testing frequency, scope coverage, third-party vs in-house testers, report sharing policy, and remediation timelines.', conf: 47, srcType: 'zoom_transcript' },
  ],
  'DOR-013': [
    { answer: 'Customers have 30 days post-termination to export all data via Admin Console or API in CSV, JSON, and Parquet formats free of charge. After this window, a staged deletion process begins over 90 days with cryptographic deletion confirmation.', conf: 50, srcType: 'zoom_transcript' },
    { answer: 'Upon contract termination, customers have 30 days to export data in open formats. After the export window, a 90-day staged deletion process begins with cryptographic proof of deletion provided.', conf: 48, srcType: 'zoom_transcript' },
  ],
  'DOR-015': [
    { answer: 'NovaPulse offers a 14-day free trial on Professional plan features, no credit card required, up to five users and 1GB storage. Key limitations: duration, user caps, storage limits, and feature restrictions.', conf: 49, srcType: 'zoom_transcript' },
    { answer: 'A SaaS free trial is a limited-time offer to evaluate the product. Important limitations: trial duration, user/storage caps, feature scope, and whether credit card details are required upfront.', conf: 49, srcType: 'zoom_transcript' },
  ],
  'DOR-017': [
    { answer: 'Annual billing is $45/user/month vs monthly at $54/user/month \u2014 approximately 15% savings with annual. Annual reduces churn risk for vendors and provides cost predictability for customers.', conf: 49, srcType: 'zoom_transcript' },
    { answer: 'Annual billing offers a discount (~15%) compared to monthly, making it more cost-effective. Monthly billing provides flexibility but at a premium. Decision depends on commitment confidence and budget cycles.', conf: 49, srcType: 'zoom_transcript' },
  ],
  'DOR-019': [
    { answer: 'An MSA is a foundational legal contract covering IP indemnification, liability caps, data privacy, portability, and termination guardrails between SaaS vendor and customer.', conf: 49, srcType: 'zoom_transcript' },
    { answer: 'An MSA outlines general terms and conditions governing the SaaS vendor-customer relationship. It typically covers liability, indemnification, data protection, termination, and portability.', conf: 49, srcType: 'zoom_transcript' },
  ],
  'DOR-020': [
    { answer: 'Vendor lock-in is dependency on a vendor\'s products making switching difficult or costly. Protect contractually via full data ownership, data portability in open formats, and explicit export rights.', conf: 49, srcType: 'gdrive_doc' },
    { answer: 'Vendor lock-in means a customer cannot easily switch vendors without substantial costs. Contractual protection includes data ownership clauses, open export formats, portability rights, and API access guarantees.', conf: 49, srcType: 'gdrive_doc' },
  ],
  'DOR-021': [
    { answer: 'An indemnification clause has one party (typically vendor) compensate the other for losses from specific events like IP infringement claims. It allocates risk and financial responsibility.', conf: 48, srcType: 'zoom_transcript' },
    { answer: 'An indemnification clause means the indemnitor compensates the indemnitee for losses from specific events (e.g., third-party IP claims). Critical for allocating legal risk in SaaS contracts.', conf: 48, srcType: 'zoom_transcript' },
  ],
  'DOR-022': [
    { answer: 'A data breach notification clause defines the vendor\'s obligation to inform customers of security incidents: timeframe for notification, information included, and a dedicated liaison contact.', conf: 48, srcType: 'zoom_transcript' },
    { answer: 'A breach notification clause obligates the vendor to inform customers in the event of a data breach. It specifies notification timeframe (e.g., 72 hours), information to provide, and responsibility chain.', conf: 48, srcType: 'zoom_transcript' },
  ],
  'DOR-025': [
    { answer: 'SCIM is a standard for automated provisioning and de-provisioning of user identities across applications and identity providers. Streamlines user management for enterprise IT.', conf: 48, srcType: 'zoom_transcript' },
    { answer: 'SCIM 2.0 enables automated provisioning/de-provisioning tied to your identity provider. Typically takes an hour to configure during onboarding for standard setups like Azure AD.', conf: 48, srcType: 'zoom_transcript' },
  ],
  'DOR-039': [
    { answer: 'The cost-of-delay framework shifts the conversation from NovaPulse\'s price to the cost of maintaining the status quo for 6\u201312 months \u2014 quantifying manual reporting hours, data reconciliation effort, and lost revenue.', conf: 49, srcType: 'gdrive_doc' },
    { answer: 'Cost-of-delay addresses budget objections by quantifying the financial impact of inaction: lost revenue, increased operational costs, and compliance risk from status-quo maintenance.', conf: 49, srcType: 'gdrive_doc' },
  ],
}

const conflictsByQidVeltrix = {
  'DOR-038': [
    { answer: 'The most effective structure follows LAER-C: Listen actively, Acknowledge concern, Explore root cause, Respond with evidence, Confirm resolution with the prospect.', conf: 0, srcType: 'unknown' },
    { answer: 'An effective structure involves: Listen Actively, Acknowledge & Empathize, Explore the root cause with clarifying questions, Respond with evidence and data, then Confirm resolution.', conf: 0, srcType: 'unknown' },
  ],
  'DOR-039': [
    { answer: 'The cost-of-delay framework involves quantifying the negative impact of not addressing the problem immediately \u2014 shifting the conversation from solution cost to cost of inaction.', conf: 0, srcType: 'unknown' },
    { answer: 'Cost-of-delay focuses on quantifying the financial impact of not implementing a solution immediately: reiterate the problem, quantify ongoing losses, compare to solution cost.', conf: 0, srcType: 'unknown' },
  ],
  'DOR-040': [
    { answer: 'A feature objection targets a specific missing capability (address with workarounds/roadmap). A fit objection questions overall alignment (address by revisiting strategic goals and demonstrating value).', conf: 0, srcType: 'unknown' },
    { answer: 'Feature objections are about specific capabilities \u2014 handled by clarifying needs and showing existing features or roadmap. Fit objections are broader \u2014 handled by revisiting strategic alignment.', conf: 0, srcType: 'unknown' },
  ],
  'DOR-041': [
    { answer: 'Acknowledge their perspective, shift focus to their unique needs, highlight differentiated outcomes and customer success stories, then propose a tailored deeper evaluation.', conf: 0, srcType: 'unknown' },
    { answer: 'Acknowledge and empathize, then differentiate by focusing on their specific pain points and outcomes rather than feature checklists. Propose a targeted evaluation or PoC.', conf: 0, srcType: 'unknown' },
  ],
  'DOR-042': [
    { answer: 'Acknowledge the analysis, verify apples-to-apples comparison, reframe to TCO/ROI and unique value differentiation, explore scope adjustments only as last resort.', conf: 0, srcType: 'unknown' },
    { answer: 'Acknowledge the homework, verify comparison methodology, reframe from per-user cost to total investment and ROI, highlight unique value, adjust scope only as last resort.', conf: 0, srcType: 'unknown' },
  ],
}

function buildDorQuestion(index, answersMap = dorAnswersByQid, srcTypesMap = sourceTypesByQid, conflictsMap = conflictsByQid) {
  const qid = `DOR-${String(index).padStart(3, '0')}`
  const row = answersMap[qid]
  const conf = row?.conf ?? 0
  const priority = conf >= 60 ? 'P1' : conf >= 40 ? 'P2' : 'P0'
  const pc = priority === 'P1' ? '#D97706' : priority === 'P2' ? '#475569' : '#DC2626'

  const rawTypes = srcTypesMap[qid] || []
  const srcs = rawTypes.length > 0
    ? rawTypes.map(t => {
        const d = SOURCE_TYPE_DISPLAY[t] || { label: t, color: '#8B949E', type: 'unknown' }
        return { name: d.label, color: d.color, type: d.type }
      })
    : []

  const conflicts = conflictsMap[qid] || []

  return {
    id: `QID-${String(index).padStart(3, '0')}`,
    text: dorQuestionTextByQid[qid] || 'Question text unavailable',
    p: priority,
    pc,
    answer: row?.answer || 'No extracted answer available in payload for this question.',
    conf,
    status: 'pending',
    override: '',
    srcs,
    conflicts,
  }
}

let dorIndex = 1
const dorSectionData = dorSections.map((section) => {
  const qs = []
  section.subsections.forEach(sub => {
    for (let i = 0; i < sub.count; i++) {
      const q = buildDorQuestion(dorIndex++)
      q.subsection = sub.title
      q.subsectionColor = sub.color
      q.subsectionIcon = sub.icon
      qs.push(q)
    }
  })
  const totalCount = section.subsections.reduce((s, sub) => s + sub.count, 0)
  return {
    id: section.id,
    title: section.title,
    icon: section.icon,
    color: section.color,
    bg: section.bg,
    signals: [
      {
        type: 'doc',
        color: '#38BDF8',
        label: section.title,
        text: `<strong>${totalCount}</strong> questions across ${section.subsections.length} areas: ${section.subsections.map(s => s.title).join(', ')}.`,
      },
      { type: 'ai', qs },
    ],
  }
})

let dorIndex2 = 1
const dorSectionDataVeltrix = dorSections.map((section) => {
  const qs = []
  section.subsections.forEach(sub => {
    for (let i = 0; i < sub.count; i++) {
      const q = buildDorQuestion(dorIndex2++, dorAnswersByQidVeltrix, sourceTypesByQidVeltrix, conflictsByQidVeltrix)
      q.subsection = sub.title
      q.subsectionColor = sub.color
      q.subsectionIcon = sub.icon
      qs.push(q)
    }
  })
  const totalCount = section.subsections.reduce((s, sub) => s + sub.count, 0)
  return {
    id: section.id,
    title: section.title,
    icon: section.icon,
    color: section.color,
    bg: section.bg,
    signals: [
      {
        type: 'doc',
        color: '#38BDF8',
        label: section.title,
        text: `<strong>${totalCount}</strong> questions across ${section.subsections.length} areas: ${section.subsections.map(s => s.title).join(', ')}.`,
      },
      { type: 'ai', qs },
    ],
  }
})

export const allSections = {
  oid0009: [
    {
      id: 'summary',
      title: 'Deal Summary',
      icon: '📊',
      color: '#38BDF8',
      bg: 'rgba(56,189,248,.1)',
      isSummary: true,
      signals: [],
      narrative: "Meridian HealthTech is evaluating a $2.8M enterprise platform to replace Salesforce Health Cloud, driven by data localisation gaps and prohibitive custom workflow costs. Champion transition (Anjali -> Priya Mehta, CTO) is the top P0 blocker and CFO David Park sign-off is required above $2M. Budget envelope is informally $2.5-3.2M pending FY25 review; no competitor contracts are signed yet.",
      risks: [
        'Champion transition and briefing gap',
        'CFO sign-off not yet fully engaged',
        'Budget formalization pending FY25 review',
      ],
      strengths: [
        'Clear decision committee structure',
        'No competing vendor contract lock-in',
        'Strong alignment with core use-case pain points',
      ],
    },
    ...dorSectionData
  ],
  'OID/112299': [
    {
      id: 'summary',
      title: 'Deal Summary',
      icon: '📊',
      color: '#38BDF8',
      bg: 'rgba(56,189,248,.1)',
      isSummary: true,
      signals: [],
      narrative: "Veltrix is a $980K SMB deal in follow-up stage. AI extraction from the DOR payload has surfaced answers across all four qualification categories, though many are conflict-sourced with 0% confidence and require manual review. Architecture, security, and sales methodology questions have the most extracted content. No direct source documents were attached — answers are based on AI knowledge resolution.",
      risks: [
        'All confidence scores at 0% — manual verification required',
        'No source documents attached to citations',
        'Single-threaded stakeholder engagement',
        'DOR-014 through DOR-032 have no extracted answers',
      ],
      strengths: [
        '22 of 42 questions have AI-generated answers from conflict resolution',
        'Full coverage across architecture, security, and sales methodology',
        'Direct answers available for BANT, MEDDIC, and multi-threading questions',
      ],
    },
    ...dorSectionDataVeltrix
  ],
}

const stubSections = (id) => {
  const opp = opps.find(o => o.id === id)
  return [
    {
      id: 'summary', title: 'Deal Summary', icon: '📊',
      color: '#38BDF8', bg: 'rgba(56,189,248,.1)',
      isSummary: true,
      signals: [],
      narrative: `AI extraction is in progress for ${opp?.name || 'this opportunity'}. Full deal summary will be available once signal extraction is complete.`,
      risks: ['Qualification incomplete — signals still being extracted'],
      strengths: [],
    },
    {
      id: 'gen', title: 'General Qualification', icon: '📋',
      color: '#79C0FF', bg: 'rgba(56,189,248,.1)',
      signals: [
        { type: 'zoom', color: '#38BDF8', label: 'Zoom · Discovery call · Jan 8', text: 'We are struggling with <strong>legacy infrastructure</strong> that can no longer scale to our current transaction volumes.' },
        { type: 'ai', qs: [
          { id: `g-${id}`, text: 'What is the primary business driver behind this initiative?', p: 'P0', pc: '#FF7B72', answer: 'Primary driver is legacy infrastructure unable to scale to growing transaction volumes.', conf: 78, status: 'pending', override: '', srcs: [{ name: 'Zoom · Discovery', color: '#38BDF8' }] }
        ]},
      ]
    }
  ]
}

;['OID/99132112','OID/343356','OID/553211','OID/771002'].forEach(id => {
  allSections[id] = stubSections(id)
})
