import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import CreateOpportunityPage from '../CreateOpportunityPage'

vi.mock('../../services/opportunitiesApi', () => ({
  createOpportunity: vi.fn(),
}))

import { createOpportunity } from '../../services/opportunitiesApi'

describe('CreateOpportunityPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls create API with form payload and triggers onCreated', async () => {
    const onCreated = vi.fn()
    createOpportunity.mockResolvedValue({ opportunity_id: 'OPP-777' })

    render(
      <CreateOpportunityPage
        user={{ email: 'qa@example.com' }}
        onBack={() => {}}
        onCreated={onCreated}
      />,
    )

    await userEvent.clear(screen.getByLabelText(/name/i))
    await userEvent.type(screen.getByLabelText(/name/i), 'Acme Expansion')
    await userEvent.click(screen.getByRole('button', { name: /create opportunity/i }))

    await waitFor(() =>
      expect(createOpportunity).toHaveBeenCalledWith({
        name: 'Acme Expansion',
      }),
    )
    expect(onCreated).toHaveBeenCalledWith('OPP-777')
  })

  it('shows API error if create fails', async () => {
    createOpportunity.mockRejectedValue(new Error('Create failed'))

    render(
      <CreateOpportunityPage
        user={{ email: 'qa@example.com' }}
        onBack={() => {}}
        onCreated={() => {}}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /create opportunity/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Create failed')
  })
})

