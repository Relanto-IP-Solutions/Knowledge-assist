import { render, screen } from '@testing-library/react'
import { QuestionCard } from '../QuestionCard'

function buildBaseProps(overrides = {}) {
  const q = {
    id: 'QID-014',
    text: 'How is pricing model handled?',
    answer: 'Per User',
    answer_value: 'Per User',
    fromApi: true,
    apiAnswerType: 'picklist',
    srcs: [],
    citations: [],
    conflicts: [],
    ...overrides.q,
  }

  const qState = {
    status: 'pending',
    override: '',
    editedAnswer: '',
    answerSource: 'ai',
    feedback: null,
    feedbackText: '',
    notes: '',
    conflictResolved: false,
    serverLocked: false,
    ...overrides.qState,
  }

  const assistReviewQuestion = {
    question_id: q.id,
    answer_type: 'picklist',
    answer_value: q.answer_value,
    answers: [
      { answer_id: 'opt-per-user', answer_value: 'Per User' },
      { answer_id: 'opt-enterprise', answer_value: 'Enterprise' },
    ],
    ...overrides.assistReviewQuestion,
  }

  return {
    q,
    oppId: 'OPP-1',
    qState,
    assistReviewQuestion,
    layout: 'assist',
    onAccept: () => {},
    onUndo: () => {},
    onSaveOverride: () => {},
    onEditOverride: () => {},
    onSaveEdit: () => {},
    onSaveFeedback: () => {},
    onResolveConflict: () => {},
    onDraftAnswerChange: () => {},
    onAssistSelectionDraft: () => {},
  }
}

describe('QuestionCard AI vs edited labels', () => {
  it('shows AI Recommended Response for backend pending answer', () => {
    render(<QuestionCard {...buildBaseProps()} />)
    expect(screen.getByText('AI RECOMMENDED RESPONSE')).toBeInTheDocument()
  })

  it('shows Accepted AI Response and keeps radio selected', () => {
    const props = buildBaseProps({
      qState: { status: 'accepted', answerSource: 'ai', editedAnswer: '' },
    })
    render(<QuestionCard {...props} />)

    expect(screen.getByText('ACCEPTED AI RESPONSE')).toBeInTheDocument()
    const perUserRadio = screen.getByRole('radio', { name: 'Per User' })
    expect(perUserRadio).toBeChecked()
  })

  it('shows Accepted Edited Response when user changed answer', () => {
    const props = buildBaseProps({
      qState: {
        status: 'accepted',
        answerSource: 'user',
        editedAnswer: 'Enterprise',
      },
    })
    render(<QuestionCard {...props} />)
    expect(screen.getByText('ACCEPTED EDITED RESPONSE')).toBeInTheDocument()
  })

  it('uses payload override flag for accepted edited label', () => {
    const props = buildBaseProps({
      q: { is_user_override: true },
      qState: { status: 'accepted', answerSource: 'ai', editedAnswer: '' },
    })
    render(<QuestionCard {...props} />)
    expect(screen.getByText('ACCEPTED EDITED RESPONSE')).toBeInTheDocument()
  })

  it('uses payload override flag for accepted ai label after reload', () => {
    const props = buildBaseProps({
      q: { is_user_override: false },
      qState: {
        status: 'accepted',
        answerSource: 'ai',
        editedAnswer: '',
      },
    })
    render(<QuestionCard {...props} />)
    expect(screen.getByText('ACCEPTED AI RESPONSE')).toBeInTheDocument()
  })
})

