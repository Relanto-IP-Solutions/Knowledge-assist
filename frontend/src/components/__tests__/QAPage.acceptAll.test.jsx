import { describe, it, expect } from 'vitest'
import { applyAcceptAllToQState } from '../QAPage'

describe('QAPage accept-all state transition', () => {
  it('accepts backend AI answers without converting to editedAnswer', () => {
    const prevQState = {
      'QID-001': {
        status: 'pending',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: false,
        serverLocked: false,
      },
      'QID-015': {
        status: 'pending',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: false,
        serverLocked: false,
      },
    }

    const apiAnswers = [
      {
        question_id: 'QID-001',
        answer_value: 'Multi-tenant',
        status: 'pending',
        answer_type: 'picklist',
      },
      {
        question_id: 'QID-015',
        answer_value: 'AI extracted narrative',
        status: 'pending',
        answer_type: 'text',
      },
    ]

    const reviewQuestions = [
      {
        question_id: 'QID-001',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'opt-1', answer_value: 'Multi-tenant' },
          { answer_id: 'opt-2', answer_value: 'Single tenant' },
        ],
      },
      {
        question_id: 'QID-015',
        answer_type: 'text',
      },
    ]

    const { next, changed } = applyAcceptAllToQState(prevQState, {
      apiAnswers,
      reviewQuestions,
      apiSelections: {},
      questionsCatalog: [],
    })

    expect(changed).toBe(2)
    expect(next['QID-001'].status).toBe('accepted')
    expect(next['QID-001'].answerSource).toBe('ai')
    expect(next['QID-001'].editedAnswer).toBe('')

    expect(next['QID-015'].status).toBe('accepted')
    expect(next['QID-015'].answerSource).toBe('ai')
    expect(next['QID-015'].editedAnswer).toBe('')
  })

  it('does not treat seeded single-select apiSelection as user edit when it matches backend', () => {
    const prevQState = {
      'QID-016': {
        status: 'pending',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: false,
        serverLocked: false,
      },
    }

    const apiAnswers = [
      {
        question_id: 'QID-016',
        answer_value: 'Yes',
        status: 'pending',
        answer_type: 'picklist',
      },
    ]

    const reviewQuestions = [
      {
        question_id: 'QID-016',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'opt-yes', answer_value: 'Yes' },
          { answer_id: 'opt-no', answer_value: 'No' },
          { answer_id: 'opt-ns', answer_value: 'Not Stated' },
        ],
      },
    ]

    const { next, changed } = applyAcceptAllToQState(prevQState, {
      apiAnswers,
      reviewQuestions,
      apiSelections: { 'QID-016': 'opt-yes' },
      questionsCatalog: [],
    })

    expect(changed).toBe(1)
    expect(next['QID-016'].status).toBe('accepted')
    expect(next['QID-016'].answerSource).toBe('ai')
    expect(next['QID-016'].editedAnswer).toBe('')
  })

  it('treats seeded single-select apiSelection as AI when backend uses answer_id', () => {
    const prevQState = {
      'QID-014': {
        status: 'pending',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: false,
        serverLocked: false,
      },
    }

    const apiAnswers = [
      {
        question_id: 'QID-014',
        answer_value: 'Per User',
        answer_id: 'opt-per-user',
        status: 'pending',
        answer_type: 'picklist',
      },
    ]

    const reviewQuestions = [
      {
        question_id: 'QID-014',
        answer_type: 'picklist',
        answers: [
          { answer_id: 'opt-per-user', answer_value: 'Per User' },
          { answer_id: 'opt-consumption', answer_value: 'Consumption-based' },
          { answer_id: 'opt-flat', answer_value: 'Flat Fee' },
        ],
      },
    ]

    const { next, changed } = applyAcceptAllToQState(prevQState, {
      apiAnswers,
      reviewQuestions,
      apiSelections: { 'QID-014': 'opt-per-user' },
      questionsCatalog: [],
    })

    expect(changed).toBe(1)
    expect(next['QID-014'].status).toBe('accepted')
    expect(next['QID-014'].answerSource).toBe('ai')
    expect(next['QID-014'].editedAnswer).toBe('')
  })

  it('keeps sparse picklist payload as accepted AI when selection is UUID', () => {
    const prevQState = {
      'QID-001': {
        status: 'pending',
        editedAnswer: '',
        override: '',
        answerSource: 'ai',
        conflictResolved: false,
        serverLocked: false,
      },
    }

    const apiAnswers = [
      {
        question_id: 'QID-001',
        answer_id: '200b18b9-adfa-4c6b-bc62-b4740482e35d',
        answer_type: 'picklist',
        answer_value: 'Hybrid',
        citations: [{ source_type: 'zoom' }],
        confidence_score: 0.5289366206075325,
        conflict_id: null,
        conflicts: [],
        current_version: 116,
        is_user_override: false,
        requirement_type: 'Required',
        status: 'pending',
      },
    ]

    // Sparse review question: option catalog may be absent in some API responses.
    const reviewQuestions = [{ question_id: 'QID-001', answer_type: 'picklist' }]

    const { next, changed } = applyAcceptAllToQState(prevQState, {
      apiAnswers,
      reviewQuestions,
      apiSelections: { 'QID-001': '200b18b9-adfa-4c6b-bc62-b4740482e35d' },
      questionsCatalog: [],
    })

    expect(changed).toBe(1)
    expect(next['QID-001'].status).toBe('accepted')
    expect(next['QID-001'].answerSource).toBe('ai')
    expect(next['QID-001'].editedAnswer).toBe('')
  })
})

