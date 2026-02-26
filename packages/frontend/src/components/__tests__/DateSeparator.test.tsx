import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DateSeparator } from '../DateSeparator'

describe('DateSeparator', () => {
  it('shows "Today" for today\'s date', () => {
    render(<DateSeparator date={new Date().toISOString()} />)
    expect(screen.getByText('Today')).toBeInTheDocument()
  })

  it('shows "Yesterday" for yesterday\'s date', () => {
    const yesterday = new Date(Date.now() - 86400000).toISOString()
    render(<DateSeparator date={yesterday} />)
    expect(screen.getByText('Yesterday')).toBeInTheDocument()
  })

  it('shows formatted date for older dates', () => {
    render(<DateSeparator date="2024-01-15T12:00:00Z" />)
    expect(screen.getByText('January 15')).toBeInTheDocument()
  })
})
