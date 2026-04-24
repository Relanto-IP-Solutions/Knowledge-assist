import { describe, it, expect } from 'vitest'
import { buildOpportunityReviewUpdates } from '../opportunityReviewMeta'

describe('submit payload generation', () => {
  it('keeps accepted AI answer on backend answer_id', () => {
    const questions = [
      {
        question_id: 'QID-001',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'aid-multi', answer_value: 'Multi-tenant' },
          { answer_id: 'aid-single', answer_value: 'Single tenant' },
        ],
      },
    ]
    const apiSelections = { 'QID-001': 'aid-multi' }
    const qState = {
      'QID-001': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-001',
        answer_id: 'aid-multi',
        answer_value: 'Multi-tenant',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    expect(updates.length).toBeGreaterThan(0)
    const row = updates.find(u => u.q_id === 'QID-001')
    expect(row).toBeTruthy()
    expect(row.answer_id).toBe('aid-multi')
    expect(row.is_user_override).toBe(false)
  })

  it('marks manual user edit as override payload', () => {
    const questions = [
      {
        question_id: 'QID-014',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'aid-per-user', answer_value: 'Per User' },
          { answer_id: 'aid-flat', answer_value: 'Flat fee' },
        ],
      },
    ]
    const apiSelections = { 'QID-014': 'aid-flat' }
    const qState = {
      'QID-014': {
        status: 'accepted',
        editedAnswer: 'Flat fee',
        override: '',
        answerSource: 'user',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-014',
        answer_id: 'aid-per-user',
        answer_value: 'Per User',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-014')
    expect(row).toBeTruthy()
    expect(Boolean(row.is_user_override)).toBe(true)
  })

  it('does not force override from stale answerSource when selection matches AI', () => {
    const questions = [
      {
        question_id: 'QID-021',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'aid-a', answer_value: 'Option A' },
          { answer_id: 'aid-b', answer_value: 'Option B' },
        ],
      },
    ]
    const apiSelections = { 'QID-021': 'aid-b' }
    const qState = {
      'QID-021': {
        status: 'accepted',
        editedAnswer: 'Option B',
        override: '',
        answerSource: 'user',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-021',
        answer_id: 'aid-a',
        answer_value: 'Option A',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-021')
    expect(row).toBeTruthy()
    expect(Boolean(row.is_user_override)).toBe(false)
  })

  it('skips invalid empty answer rows', () => {
    const questions = [{ question_id: 'QID-999', answer_type: 'text' }]
    const apiSelections = {}
    const qState = {
      'QID-999': { status: 'pending', editedAnswer: '', override: '' },
    }
    const rawAnswerRows = [{ question_id: 'QID-999', answer_value: '', status: 'pending' }]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-999')
    expect(row).toBeFalsy()
  })

  it('sends full multi-select override_value array from UI ticks', () => {
    const questions = [
      {
        question_id: 'QID-004',
        answer_type: 'multi_select',
        answers: [
          { answer_id: 'opt-rest', answer_value: 'REST' },
          { answer_id: 'opt-graphql', answer_value: 'GraphQL' },
          { answer_id: 'opt-soap', answer_value: 'SOAP' },
          { answer_id: 'opt-grpc', answer_value: 'gRPC' },
        ],
      },
    ]
    const apiSelections = { 'QID-004': ['opt-rest', 'opt-graphql', 'opt-soap'] }
    const qState = {
      'QID-004': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-004',
        answer_id: 'row-uuid-004',
        answer_value: "['REST']",
        answer_type: 'multi_select',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-004')
    expect(row).toBeTruthy()
    expect(Boolean(row.is_user_override)).toBe(true)
    expect(typeof row.override_value).toBe('string')
    expect(row.override_value).toBe('["REST", "GraphQL", "SOAP"]')
  })

  it('does not mark override when multi baseline is comma-separated and unchanged', () => {
    const questions = [
      {
        question_id: 'QID-004',
        answer_type: 'multi_select',
        answers: [
          { answer_id: '11111111-1111-4111-8111-111111111111', answer_value: 'Multi tenant' },
          { answer_id: '22222222-2222-4222-8222-222222222222', answer_value: 'Hybrid' },
        ],
      },
    ]
    const apiSelections = {
      'QID-004': [
        '11111111-1111-4111-8111-111111111111',
        '22222222-2222-4222-8222-222222222222',
      ],
    }
    const qState = {
      'QID-004': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-004',
        answer_id: '95cc6efd-db46-4aae-8fa6-53a515fec156',
        answer_value: 'Multi tenant, Hybrid',
        answer_type: 'multi_select',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-004')
    expect(row).toBeTruthy()
    expect(row.answer_id).toBe('95cc6efd-db46-4aae-8fa6-53a515fec156')
    expect(Boolean(row.is_user_override)).toBe(false)
    expect(row.override_value).toBeUndefined()
  })

  it('Accept-All on unopened section: UUID selection matching AI answer is not flagged as override', () => {
    /**
     * Simulates the Accept-All flow for a section that was never opened:
     * - apiSelections is pre-seeded with the UUID from final_answer_id (not a user choice)
     * - qState has no editedAnswer (section UI never rendered / draft-sync never ran)
     * - The UUID selection matches the backend AI answer → is_user_override must be false
     */
    const questions = [
      {
        question_id: 'QID-ACCEPTALL',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'uuid-yes', answer_value: 'Yes' },
          { answer_id: 'uuid-no', answer_value: 'No' },
        ],
      },
    ]
    // Pre-seeded UUID selection — same option as the AI answer
    const apiSelections = { 'QID-ACCEPTALL': 'uuid-yes' }
    const qState = {
      'QID-ACCEPTALL': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        acceptedAnswerValue: 'Yes',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-ACCEPTALL',
        answer_id: 'uuid-yes',
        answer_value: 'Yes',
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-ACCEPTALL')
    expect(row).toBeTruthy()
    expect(row.answer_id).toBe('uuid-yes')
    expect(Boolean(row.is_user_override)).toBe(false)
  })

  it('uses human-readable answer_value when conflict selection is an answer_id', () => {
    const conflictAnswerId = '11111111-1111-4111-8111-111111111111'
    const questions = [
      {
        question_id: 'QID-099',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'fallback-opt', answer_value: 'Fallback Option' },
        ],
      },
    ]
    const apiSelections = { 'QID-099': conflictAnswerId }
    const qState = {
      'QID-099': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: true,
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-099',
        answer_id: 'row-answer-id',
        answer_value: 'Fallback Option',
        conflict_id: 'conflict-1',
        conflicts: [
          {
            answer_id: conflictAnswerId,
            answer_value: 'Per User',
          },
        ],
        status: 'pending',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-099')
    expect(row).toBeTruthy()
    expect(row.answer_id).toBe('row-answer-id')
    expect(row.conflict_answer_id).toBe(conflictAnswerId)
    expect(Boolean(row.is_user_override)).toBe(false)
    expect(row.answer_value).toBe('Per User')
    expect(row.answer_value).not.toBe(conflictAnswerId)
  })

  it('preserves persisted override intent even when value equals baseline', () => {
    const questions = [
      {
        question_id: 'QID-PRESERVE-OVERRIDE',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'uuid-a', answer_value: 'Option A' },
          { answer_id: 'uuid-b', answer_value: 'Option B' },
        ],
      },
    ]
    const apiSelections = { 'QID-PRESERVE-OVERRIDE': 'uuid-a' }
    const qState = {
      'QID-PRESERVE-OVERRIDE': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
      },
    }
    const rawAnswerRows = [
      {
        question_id: 'QID-PRESERVE-OVERRIDE',
        answer_id: 'uuid-a',
        answer_value: 'Option A',
        is_user_override: true,
        status: 'active',
      },
    ]

    const updates = buildOpportunityReviewUpdates(questions, apiSelections, { qState, rawAnswerRows })
    const row = updates.find(u => u.q_id === 'QID-PRESERVE-OVERRIDE')
    expect(row).toBeTruthy()
    expect(row.answer_id).toBe('uuid-a')
    expect(Boolean(row.is_user_override)).toBe(true)
  })
})

