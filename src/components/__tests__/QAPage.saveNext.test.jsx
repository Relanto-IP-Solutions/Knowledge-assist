import { describe, it, expect } from 'vitest'
import { isQuestionComplete } from '../QAPage'

describe('QAPage Save & Next completion logic', () => {
  it('treats accepted backend AI answer as complete', () => {
    const question = {
      question_id: 'QID-014',
      answer_type: 'picklist',
      answer_value: 'Per User',
    }
    const qStateEntry = {
      status: 'accepted',
      editedAnswer: '',
      override: '',
      answerSource: 'ai',
      complete: false,
    }
    expect(isQuestionComplete(question, qStateEntry)).toBe(true)
  })

  it('returns false for accepted question with no backend/manual value', () => {
    const question = {
      question_id: 'QID-006',
      answer_type: 'integer',
      answer_value: null,
    }
    const qStateEntry = {
      status: 'accepted',
      editedAnswer: '',
      override: '',
      answerSource: 'ai',
      complete: false,
    }
    expect(isQuestionComplete(question, qStateEntry)).toBe(false)
  })
})

