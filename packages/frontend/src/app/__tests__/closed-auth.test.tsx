import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Home from '../page'
import LoginPage from '../login/page'

const login = vi.fn()

vi.mock('@/lib/auth', () => ({
  useAuth: Object.assign(
    () => ({ user: null, isLoading: false, login }),
    { getState: () => ({ logout: vi.fn() }) }
  ),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

describe('closed authentication surface', () => {
  beforeEach(() => login.mockReset())

  it('shows sign in without an account creation link on the home page', () => {
    render(<Home />)

    expect(screen.getByRole('link', { name: 'Sign In' })).toHaveAttribute(
      'href',
      '/login'
    )
    expect(screen.queryByText('Create Account')).not.toBeInTheDocument()
  })

  it('does not advertise registration on the login page', () => {
    render(<LoginPage />)

    expect(screen.getByRole('heading', { name: 'Sign In' })).toBeInTheDocument()
    expect(screen.queryByText(/Don\u2019t have an account/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Create one/i })).not.toBeInTheDocument()
  })
})
