import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SearchPage from '../search/page'

const { search } = vi.hoisted(() => ({ search: vi.fn() }))

vi.mock('@/lib/api', () => ({ api: { search } }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { id: 'owner' }, isLoading: false }),
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => null }))

function result(id: string, telegramMessageId: number) {
  return {
    id,
    chat_id: 'chat-1',
    chat_title: 'Saved Messages',
    chat_type: 'private',
    chat_telegram_id: 1,
    telegram_message_id: telegramMessageId,
    text: `Result ${telegramMessageId}`,
    sender_name: 'Owner',
    is_outgoing: true,
    sent_at: '2026-08-07T09:00:00Z',
    similarity: 0.9,
    has_media: false,
  }
}

describe('search cursor pagination', () => {
  beforeEach(() => {
    search.mockReset()
    search
      .mockResolvedValueOnce({
        results: [result('message-1', 1)],
        total: 1,
        has_more: true,
        next_cursor: 'next-page',
      })
      .mockResolvedValueOnce({
        results: [result('message-2', 2)],
        total: 1,
        has_more: false,
        next_cursor: null,
      })
  })

  it('loads every page using the opaque next cursor', async () => {
    const user = userEvent.setup()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <SearchPage />
      </QueryClientProvider>
    )

    await user.type(screen.getByRole('textbox'), 'roadmap')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Result 1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Load more results' }))
    expect(await screen.findByText('Result 2')).toBeInTheDocument()
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2))
    expect(search).toHaveBeenNthCalledWith(1, 'roadmap', undefined, 20, undefined)
    expect(search).toHaveBeenNthCalledWith(
      2,
      'roadmap',
      undefined,
      20,
      'next-page'
    )
    expect(
      screen.queryByRole('button', { name: 'Load more results' })
    ).not.toBeInTheDocument()
  })
})
