import { afterEach, describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MessageBubble } from '../MessageBubble'
import { api, type Message } from '@/lib/api'

const baseMessage: Message = {
  id: 'msg-1',
  telegram_message_id: 1,
  text: 'Hello world',
  has_media: false,
  media_type: null,
  sender_id: 12345,
  sender_name: 'Alice',
  is_outgoing: false,
  sent_at: '2024-01-15T14:30:00Z',
  transcribed_at: null,
}

describe('MessageBubble', () => {
  afterEach(() => vi.restoreAllMocks())

  const renderWithQuery = (message: Message) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MessageBubble
          chatId="chat-1"
          message={message}
          isFirstInGroup={true}
          isLastInGroup={true}
          isDark={false}
        />
      </QueryClientProvider>
    )
  }

  it('renders message text', () => {
    render(
      <MessageBubble
        chatId="chat-1"
        message={baseMessage}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('shows sender name for first in group incoming', () => {
    render(
      <MessageBubble
        chatId="chat-1"
        message={baseMessage}
        isFirstInGroup={true}
        isLastInGroup={false}
        isDark={false}
      />
    )
    expect(screen.getByText('Alice')).toBeInTheDocument()
  })

  it('hides sender name for non-first in group', () => {
    render(
      <MessageBubble
        chatId="chat-1"
        message={baseMessage}
        isFirstInGroup={false}
        isLastInGroup={false}
        isDark={false}
      />
    )
    expect(screen.queryByText('Alice')).not.toBeInTheDocument()
  })

  it('hides sender name for outgoing messages', () => {
    render(
      <MessageBubble
        chatId="chat-1"
        message={{ ...baseMessage, is_outgoing: true }}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    expect(screen.queryByText('Alice')).not.toBeInTheDocument()
  })

  it('shows timestamp in HH:mm format', () => {
    const { container } = render(
      <MessageBubble
        chatId="chat-1"
        message={baseMessage}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    // Timestamp depends on local timezone, just verify it's present and formatted
    const timestampEl = container.querySelector('.text-timestamp')
    expect(timestampEl).toBeInTheDocument()
    expect(timestampEl?.textContent).toMatch(/^\d{2}:\d{2}$/)
  })

  it('shows media type when text is null', () => {
    render(
      <MessageBubble
        chatId="chat-1"
        message={{ ...baseMessage, text: null, has_media: true, media_type: 'photo' }}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    expect(screen.getByText('[photo]')).toBeInTheDocument()
  })

  it('shows transcription icon when transcribed', () => {
    const { container } = render(
      <MessageBubble
        chatId="chat-1"
        message={{ ...baseMessage, transcribed_at: '2024-01-15T15:00:00Z' }}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    const svg = container.querySelector('svg')
    expect(svg).toBeInTheDocument()
  })

  it('prepares uncached media and exposes explicit progress', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getMessageContent').mockResolvedValue({
      id: 'msg-1',
      telegram_message_id: 1,
      text: null,
      media_type: 'audio',
      media_file_name: 'meeting.mp3',
      media_mime_type: 'audio/mpeg',
      media_file_size: 100,
      media_duration_seconds: 5,
      content_text: null,
      content_summary: null,
      media_processing_status: 'failed',
      media_processing_error_code: null,
      media_processing_error: null,
      transcribed_at: null,
      media_processed_at: null,
      content_model: null,
      summary_model: null,
      telegram_message_url: 'https://t.me/c/1/1',
      media_download_url: null,
      media_cache_status: 'failed',
      media_cache_stage: 'fetch',
      media_sha256: null,
      media_cached_bytes: 25,
      next_action: 'Call prepare_media',
    })
    const prepare = vi.spyOn(api, 'prepareMessageMedia').mockResolvedValue({
      message_id: 'msg-1', status: 'pending', stage: 'fetch', byte_offset: 25,
      size_bytes: 100, sha256: null, retry_after: null, error_code: null,
      error_detail: null, media_download_url: null, next_action: 'Refresh progress',
    })

    renderWithQuery({ ...baseMessage, text: null, has_media: true, media_type: 'audio', media_file_name: 'meeting.mp3' })
    await user.click(screen.getByRole('button', { name: 'Media details' }))
    await user.click(await screen.findByRole('button', { name: 'Prepare media' }))

    expect(prepare).toHaveBeenCalledWith('chat-1', 1)
  })

  it('shows active download progress without starting a duplicate prepare', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getMessageContent').mockResolvedValue({
      id: 'msg-1', telegram_message_id: 1, text: null, media_type: 'video',
      media_file_name: 'large.mp4', media_mime_type: 'video/mp4', media_file_size: 100,
      media_duration_seconds: 10, content_text: null, content_summary: null,
      media_processing_status: 'processing', media_processing_error_code: null,
      media_processing_error: null, transcribed_at: null, media_processed_at: null,
      content_model: null, summary_model: null, telegram_message_url: 'https://t.me/c/1/1',
      media_download_url: null, media_cache_status: 'fetching', media_cache_stage: 'fetch',
      media_sha256: null, media_cached_bytes: 25, next_action: 'Refresh progress',
    })
    const prepare = vi.spyOn(api, 'prepareMessageMedia')

    renderWithQuery({ ...baseMessage, text: null, has_media: true, media_type: 'video', media_file_name: 'large.mp4' })
    await user.click(screen.getByRole('button', { name: 'Media details' }))

    expect(await screen.findByText('25% · 25 B / 100 B')).toBeInTheDocument()
    expect(screen.getByText('Processing continues in the background.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Prepare media' })).not.toBeInTheDocument()
    expect(prepare).not.toHaveBeenCalled()
  })

  it('renders ready media, links, hash and cursor-paginated transcript', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getMessageContent').mockResolvedValue({
      id: 'msg-1', telegram_message_id: 1, text: null, media_type: 'audio',
      media_file_name: 'meeting.mp3', media_mime_type: 'audio/mpeg', media_file_size: 2048,
      media_duration_seconds: 10, content_text: 'Full transcript', content_summary: 'Summary',
      media_processing_status: 'ready', media_processing_error_code: null,
      media_processing_error: null, transcribed_at: '2024-01-15T15:00:00Z',
      media_processed_at: '2024-01-15T15:01:00Z', content_model: 'nova-3',
      summary_model: 'gpt-5.6-luna', telegram_message_url: 'https://t.me/c/1/1',
      media_download_url: '/api/v1/chats/chat-1/messages/1/media?token=signed',
      media_cache_status: 'ready', media_cache_stage: 'complete', media_sha256: 'a'.repeat(64),
      media_cached_bytes: 2048, next_action: null,
    })
    vi.spyOn(api, 'getTranscriptSegments').mockImplementation(async (_chatId, _messageId, cursor) => (
      cursor === 0
        ? { segments: [{ sequence: 0, start_ms: 0, end_ms: 1000, speaker: 'A', confidence: 0.9, language: 'ru', text: 'first segment' }], has_more: true, next_cursor: 1 }
        : { segments: [{ sequence: 1, start_ms: 1000, end_ms: 2000, speaker: 'B', confidence: 0.8, language: 'ru', text: 'second segment' }], has_more: false, next_cursor: null }
    ))
    const message = {
      ...baseMessage,
      text: null,
      has_media: true,
      media_type: 'audio',
      media_file_name: 'meeting.mp3',
      visible_urls: ['https://example.com/visible'],
      hidden_urls: ['https://example.com/hidden'],
    }

    const rendered = renderWithQuery(message)
    await user.click(screen.getByRole('button', { name: 'Media details' }))

    const download = await screen.findByRole('link', { name: /Download original/ })
    expect(download).toHaveAttribute('download')
    expect(screen.getByRole('link', { name: 'Open in Telegram' })).toHaveAttribute('href', 'https://t.me/c/1/1')
    expect(screen.getByRole('link', { name: 'https://example.com/hidden' })).toBeInTheDocument()
    expect(screen.getByText(`SHA-256 ${'a'.repeat(64)}`)).toBeInTheDocument()
    expect(rendered.container.querySelector('audio')).toHaveAttribute('controls')
    expect(await screen.findByText('first segment')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Load more transcript' }))
    expect(await screen.findByText('second segment')).toBeInTheDocument()
  })
})
