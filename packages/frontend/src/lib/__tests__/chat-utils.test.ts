import { describe, it, expect } from 'vitest'
import {
  getSenderColor,
  getInitials,
  getInitialsColor,
  formatMessageTime,
  formatDateSeparator,
  shouldShowDateSeparator,
  formatChatListTime,
  isSameGroup,
} from '../chat-utils'

describe('getSenderColor', () => {
  it('returns deterministic color for same sender', () => {
    const c1 = getSenderColor(12345, false)
    const c2 = getSenderColor(12345, false)
    expect(c1).toBe(c2)
  })

  it('returns different lightness for dark mode', () => {
    const light = getSenderColor(12345, false)
    const dark = getSenderColor(12345, true)
    expect(light).not.toBe(dark)
    expect(dark).toContain('80%, 65%')
    expect(light).toContain('70%, 45%')
  })

  it('accepts string sender id', () => {
    const color = getSenderColor('user-abc', false)
    expect(color).toMatch(/^hsl\(\d+, 70%, 45%\)$/)
  })
})

describe('getInitials', () => {
  it('returns two chars for single word', () => {
    expect(getInitials('Alice')).toBe('AL')
  })

  it('returns first letter of each word for two words', () => {
    expect(getInitials('John Doe')).toBe('JD')
  })

  it('returns ? for empty string', () => {
    expect(getInitials('')).toBe('?')
  })

  it('returns ? for whitespace only', () => {
    expect(getInitials('   ')).toBe('?')
  })

  it('uses first two words only', () => {
    expect(getInitials('A B C D')).toBe('AB')
  })
})

describe('getInitialsColor', () => {
  it('returns deterministic color for same title', () => {
    expect(getInitialsColor('Test')).toBe(getInitialsColor('Test'))
  })

  it('returns hsl format', () => {
    expect(getInitialsColor('Chat')).toMatch(/^hsl\(\d+, 55%, 50%\)$/)
  })
})

describe('formatMessageTime', () => {
  it('formats ISO date to HH:mm pattern', () => {
    const result = formatMessageTime('2024-01-15T14:30:00Z')
    // Result depends on local timezone, just verify the format
    expect(result).toMatch(/^\d{2}:\d{2}$/)
  })
})

describe('formatDateSeparator', () => {
  it('returns "Today" for today', () => {
    const today = new Date().toISOString()
    expect(formatDateSeparator(today)).toBe('Today')
  })

  it('returns "Yesterday" for yesterday', () => {
    const yesterday = new Date(Date.now() - 86400000).toISOString()
    expect(formatDateSeparator(yesterday)).toBe('Yesterday')
  })

  it('returns formatted date for older dates', () => {
    expect(formatDateSeparator('2024-01-15T12:00:00Z')).toBe('January 15')
  })
})

describe('shouldShowDateSeparator', () => {
  it('returns true when no previous date', () => {
    expect(shouldShowDateSeparator('2024-01-15T12:00:00Z', null)).toBe(true)
  })

  it('returns false for same day', () => {
    expect(
      shouldShowDateSeparator('2024-01-15T14:00:00Z', '2024-01-15T10:00:00Z')
    ).toBe(false)
  })

  it('returns true for different days', () => {
    expect(
      shouldShowDateSeparator('2024-01-16T10:00:00Z', '2024-01-15T10:00:00Z')
    ).toBe(true)
  })
})

describe('formatChatListTime', () => {
  it('returns time for today', () => {
    const now = new Date()
    now.setHours(14, 30, 0, 0)
    const result = formatChatListTime(now.toISOString())
    expect(result).toContain(':30')
  })

  it('returns "Yesterday" for yesterday', () => {
    const yesterday = new Date(Date.now() - 86400000)
    yesterday.setHours(12, 0, 0, 0)
    expect(formatChatListTime(yesterday.toISOString())).toBe('Yesterday')
  })
})

describe('isSameGroup', () => {
  it('returns false when no previous message', () => {
    expect(
      isSameGroup(
        { sender_id: 1, sent_at: '2024-01-15T12:00:00Z', is_outgoing: false },
        null
      )
    ).toBe(false)
  })

  it('returns true for same sender within 3 minutes', () => {
    expect(
      isSameGroup(
        { sender_id: 1, sent_at: '2024-01-15T12:02:00Z', is_outgoing: false },
        { sender_id: 1, sent_at: '2024-01-15T12:00:00Z', is_outgoing: false }
      )
    ).toBe(true)
  })

  it('returns false for different senders', () => {
    expect(
      isSameGroup(
        { sender_id: 1, sent_at: '2024-01-15T12:01:00Z', is_outgoing: false },
        { sender_id: 2, sent_at: '2024-01-15T12:00:00Z', is_outgoing: false }
      )
    ).toBe(false)
  })

  it('returns false when outgoing direction differs', () => {
    expect(
      isSameGroup(
        { sender_id: 1, sent_at: '2024-01-15T12:01:00Z', is_outgoing: true },
        { sender_id: 1, sent_at: '2024-01-15T12:00:00Z', is_outgoing: false }
      )
    ).toBe(false)
  })

  it('returns false when time gap exceeds 3 minutes', () => {
    expect(
      isSameGroup(
        { sender_id: 1, sent_at: '2024-01-15T12:05:00Z', is_outgoing: false },
        { sender_id: 1, sent_at: '2024-01-15T12:00:00Z', is_outgoing: false }
      )
    ).toBe(false)
  })
})
