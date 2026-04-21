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
})

