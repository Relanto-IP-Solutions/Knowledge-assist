-- =========================================================
-- Migration: Reframe SASE Questions and Prompts
-- File: reframe_sase_questions_and_prompts.sql
-- Description:
--   - Rewrites all 42 questions to meaningful, contextual questions
--   - Aligns question_prompt with LLM-friendly instructions
--   - Preserves all other columns
--   - Assumes backup table already exists: sase_questions_backup
-- =========================================================

BEGIN;

-- =========================================================
-- UPDATE QUESTIONS + PROMPTS
-- =========================================================

UPDATE sase_questions
SET
question = CASE q_id

-- SASE TECH FUNDAMENTALS
WHEN 'QID-001' THEN 'What is the SaaS architecture type used by the solution?'
WHEN 'QID-002' THEN 'How is the solution delivered in terms of cloud-native architecture?'
WHEN 'QID-003' THEN 'What type of auto-scaling capability does the solution support?'
WHEN 'QID-004' THEN 'What API architecture styles are supported by the solution?'
WHEN 'QID-005' THEN 'What is the service availability SLA offered by the solution?'
WHEN 'QID-006' THEN 'What is the disaster recovery time objective offered by the solution?'
WHEN 'QID-007' THEN 'What data encryption standards are implemented by the solution?'

-- SECURITY FUNDAMENTALS
WHEN 'QID-008' THEN 'What access control model is used by the solution?'
WHEN 'QID-009' THEN 'What database isolation level is implemented in the solution?'
WHEN 'QID-010' THEN 'What is the audit logging retention period?'
WHEN 'QID-011' THEN 'What is the frequency of vulnerability scanning?'
WHEN 'QID-012' THEN 'How frequently are penetration tests conducted?'
WHEN 'QID-013' THEN 'What is the SOC 2 compliance status of the solution?'

-- PRICING & PACKAGING
WHEN 'QID-014' THEN 'What type of licensing model does the solution use?'
WHEN 'QID-015' THEN 'What are the details of the pricing model?'
WHEN 'QID-016' THEN 'Does the solution offer a freemium Support?'
WHEN 'QID-017' THEN 'Is user-based seat pricing supported?'
WHEN 'QID-018' THEN 'Does the solution support flat rate pricing?'

-- COMMERCIAL TERMS
WHEN 'QID-019' THEN 'What are the indemnification terms defined in the agreement?'
WHEN 'QID-020' THEN 'What is the breach notification window?'
WHEN 'QID-021' THEN 'What are the SLA credit terms defined in the agreement?'
WHEN 'QID-022' THEN 'Does the agreement include termination for convenience?'
WHEN 'QID-023' THEN 'What key clauses are included in the MSA negotiations?'

-- INTEGRATION ARCHITECTURE
WHEN 'QID-024' THEN 'Does the solution provide API support for integration?'
WHEN 'QID-025' THEN 'What type of real-time synchronization mechanism is supported?'
WHEN 'QID-026' THEN 'What type of iPaaS or integration approach is used?'
WHEN 'QID-027' THEN 'What type of integration connectors are supported?'
WHEN 'QID-028' THEN 'What are the challenges associated with integrating the solution?'

-- IMPLEMENTATION BEST PRACTICES
WHEN 'QID-029' THEN 'What is the strategy for running parallel systems during the implementation?'
WHEN 'QID-030' THEN 'What is the process followed for the data migration?'
WHEN 'QID-031' THEN 'What is the approach for executing the pilot programs?'
WHEN 'QID-032' THEN 'What is the strategy used to drive the user adoption?'

-- SALES METHODOLOGY
WHEN 'QID-033' THEN 'What is the discovery process followed during the sales cycle?'
WHEN 'QID-034' THEN 'What is the qualification framework used to assess opportunities?'
WHEN 'QID-035' THEN 'What are the most common objections encountered during the sales cycle?'
WHEN 'QID-036' THEN 'How are the pricing-related objections handled?' 
WHEN 'QID-037' THEN 'What sales engagement approach or style is used?'

-- OBJECTION HANDLING
WHEN 'QID-038' THEN 'How are the security-related objections addressed?'
WHEN 'QID-039' THEN 'What factors contribute to the successful implementation?'
WHEN 'QID-040' THEN 'What is the cost of delaying the implementation?'
WHEN 'QID-041' THEN 'What are the types of objection handling?'
WHEN 'QID-042' THEN 'How is system uptime assessed and communicated?'

END,

question_prompt = CASE q_id

WHEN 'QID-001' THEN 'Identify the SaaS architecture type of the solution. Return as a picklist using only: Multi-tenant, Single-tenant, Hybrid, Other.'
WHEN 'QID-002' THEN 'Identify how the solution is delivered in terms of cloud-native architecture. Return as a picklist using only: Fully Cloud-Native, Lift-and-Shift, Containerized Legacy.'
WHEN 'QID-003' THEN 'Identify the auto-scaling capability of the solution. Return as a picklist using only: Horizontal, Vertical, None.'
WHEN 'QID-004' THEN 'Identify the API architecture styles supported by the solution. Return as multi-select using only: REST, GraphQL, SOAP, gRPC.'
WHEN 'QID-005' THEN 'Extract the service availability SLA (uptime percentage). Return as an integer or null.'
WHEN 'QID-006' THEN 'Extract the disaster recovery RTO in minutes. Return as an integer or null.'
WHEN 'QID-007' THEN 'Identify the data encryption standards used. Return as multi-select using only: AES-256, RSA, TLS 1.3, PGP.'

WHEN 'QID-008' THEN 'Identify the access control model used. Return as a picklist using only: RBAC, ABAC, MAC, DAC, Other.'
WHEN 'QID-009' THEN 'Identify the database isolation level used. Return as a picklist using only: Row-level, Schema-level, Shared.'
WHEN 'QID-010' THEN 'Extract the audit logging retention period. Return as an integer or null.'
WHEN 'QID-011' THEN 'Identify the vulnerability scanning frequency. Return as a picklist using only: Daily, Weekly, Monthly, Real-time.'
WHEN 'QID-012' THEN 'Identify the penetration testing frequency. Return as a picklist using only: Quarterly, Semi-Annually, Annually, Continuous.'
WHEN 'QID-013' THEN 'Identify the SOC 2 compliance status. Return as a picklist using only: Type 1, Type 2, Not Compliant, In Progress.'

WHEN 'QID-014' THEN 'Identify the licensing model. Return as a picklist using only: Per User, Consumption-based, Flat Fee.'
WHEN 'QID-015' THEN 'Extract the pricing model details. Return as text verbatim or null.'
WHEN 'QID-016' THEN 'Identify whether a freemium model is supported. Return as a picklist: Yes, No, Not Stated.'
WHEN 'QID-017' THEN 'Identify whether user seat pricing is supported. Return as a picklist: Yes, No, Not Stated.'
WHEN 'QID-018' THEN 'Identify whether flat rate pricing is supported. Return as a picklist: Yes, No, Not Stated.'

WHEN 'QID-019' THEN 'Extract the indemnification clause details. Return as text verbatim from the context.'
WHEN 'QID-020' THEN 'Extract the breach notification window. Return as an integer or null.'
WHEN 'QID-021' THEN 'Extract SLA credit clause details. Return as text verbatim or null.'
WHEN 'QID-022' THEN 'Identify if termination for convenience is allowed. Return as a picklist: Yes, No, Mutual.'
WHEN 'QID-023' THEN 'Identify key MSA negotiation clauses. Return as multi-select using only: Limitation of Liability, IP Rights, Privacy, Jurisdiction, Audit.'

WHEN 'QID-024' THEN 'Identify API support availability. Return as a picklist: Yes, No, Private Only.'
WHEN 'QID-025' THEN 'Identify the real-time synchronization mechanism. Return as a picklist: Webhooks, Polling, Event Stream, None.'
WHEN 'QID-026' THEN 'Identify the iPaaS or integration type used. Return as a picklist: Native Integration, iPaaS, Hybrid, Other.'
WHEN 'QID-027' THEN 'Identify the connector type used. Return as a picklist: Native, Third-party, Both.'
WHEN 'QID-028' THEN 'Extract integration challenges. Return as text verbatim or null.'

WHEN 'QID-029' THEN 'Identify the parallel run strategy. Return as a picklist: Yes, No, Planned, Not Started.'
WHEN 'QID-030' THEN 'Extract the data migration process. Return as text verbatim or null.'
WHEN 'QID-031' THEN 'Identify the pilot program strategy. Return as a picklist: Standard, Custom, None.'
WHEN 'QID-032' THEN 'Extract the user adoption strategy. Return as text verbatim or null.'

WHEN 'QID-033' THEN 'Extract the discovery process. Return as text verbatim or null.'
WHEN 'QID-034' THEN 'Extract the qualification framework. Return as text verbatim or null.'
WHEN 'QID-035' THEN 'Extract common sales objections. Return as text verbatim or null.'
WHEN 'QID-036' THEN 'Extract how pricing objections are handled. Return as text verbatim or null.'
WHEN 'QID-037' THEN 'Extract the sales engagement style. Return as text verbatim or null.'

WHEN 'QID-038' THEN 'Extract how security objections are handled. Return as text verbatim or null.'
WHEN 'QID-039' THEN 'Extract implementation success factors. Return as text verbatim or null.'
WHEN 'QID-040' THEN 'Extract the cost of delay. Return as text verbatim or null.'   
WHEN 'QID-041' THEN 'Extract objection types encountered. Return as text verbatim or null.'
WHEN 'QID-042' THEN 'Extract uptime assessment details. Return as text verbatim or null.'

END
WHERE q_id IN (
'QID-001','QID-002','QID-003','QID-004','QID-005','QID-006','QID-007',
'QID-008','QID-009','QID-010','QID-011','QID-012','QID-013',
'QID-014','QID-015','QID-016','QID-017','QID-018',
'QID-019','QID-020','QID-021','QID-022','QID-023',
'QID-024','QID-025','QID-026','QID-027','QID-028',
'QID-029','QID-030','QID-031','QID-032',
'QID-033','QID-034','QID-035','QID-036','QID-037',
'QID-038','QID-039','QID-040','QID-041','QID-042'
);

COMMIT;

-- =========================================================
-- POST-MIGRATION VALIDATION QUERY
-- =========================================================
-- Run separately if needed:
-- SELECT q_id, question, question_prompt FROM sase_questions ORDER BY q_id;
