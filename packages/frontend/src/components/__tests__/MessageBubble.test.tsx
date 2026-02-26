import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageBubble } from '../MessageBubble'
import type { Message } from '@/lib/api'

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
  it('renders message text', () => {
    render(
      <MessageBubble
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
        message={{ ...baseMessage, transcribed_at: '2024-01-15T15:00:00Z' }}
        isFirstInGroup={true}
        isLastInGroup={true}
        isDark={false}
      />
    )
    const svg = container.querySelector('svg')
    expect(svg).toBeInTheDocument()
  })
})
