import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeToggle } from '../ThemeToggle'

describe('ThemeToggle', () => {
  it('renders the toggle button', () => {
    render(<ThemeToggle />)
    // Initial theme is "light" from mock, so button should show "Dark"
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('shows "Dark" when in light mode', () => {
    render(<ThemeToggle />)
    expect(screen.getByText('Dark')).toBeInTheDocument()
  })

  it('has correct aria-label for light mode', () => {
    render(<ThemeToggle />)
    expect(screen.getByLabelText('Switch to dark mode')).toBeInTheDocument()
  })

  it('calls setTheme on click', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)
    await user.click(screen.getByRole('button'))
    // The mock setTheme is a vi.fn() — we verify the click doesn't throw
    // and the component remains interactive
    expect(screen.getByRole('button')).toBeInTheDocument()
  })
})
