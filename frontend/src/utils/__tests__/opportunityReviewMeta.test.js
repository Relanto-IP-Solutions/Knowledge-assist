import {
  isQuestionRequired,
  validateRequiredReviewQuestions,
} from '../opportunityReviewMeta'

describe('opportunityReviewMeta required validation', () => {
  it('detects required questions from requirement_type', () => {
    expect(isQuestionRequired({ requirement_type: 'required' })).toBe(true)
    expect(isQuestionRequired({ requirement_type: 'optional' })).toBe(false)
  })

  it('treats accepted backend AI value as complete', () => {
    const questions = [
      {
        question_id: 'QID-001',
        requirement_type: 'required',
        answer_type: 'picklist',
      },
    ]
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
        answer_value: 'Multi-tenant',
      },
    ]

    const result = validateRequiredReviewQuestions(questions, {}, qState, { rawAnswerRows })
    expect(result.ok).toBe(true)
    expect(result.errorsByQid).toEqual({})
  })

  it('fails required validation for accepted with no answer', () => {
    const questions = [
      {
        question_id: 'QID-005',
        requirement_type: 'required',
        answer_type: 'integer',
      },
    ]
    const qState = {
      'QID-005': {
        status: 'accepted',
        editedAnswer: '',
        override: '',
      },
    }

    const result = validateRequiredReviewQuestions(questions, {}, qState, { rawAnswerRows: [] })
    expect(result.ok).toBe(false)
    expect(result.errorsByQid['QID-005']).toBe('This answer is required')
  })
})

