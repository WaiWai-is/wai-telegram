import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatAvatar } from '../ChatAvatar'

describe('ChatAvatar', () => {
  it('renders initials from title', () => {
    render(<ChatAvatar title="John Doe" />)
    expect(screen.getByText('JD')).toBeInTheDocument()
  })

  it('renders two-char initials for single word', () => {
    render(<ChatAvatar title="Alice" />)
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('applies default size of 48', () => {
    const { container } = render(<ChatAvatar title="Test" />)
    const el = container.firstChild as HTMLElement
    expect(el.style.width).toBe('48px')
    expect(el.style.height).toBe('48px')
  })

  it('applies custom size', () => {
    const { container } = render(<ChatAvatar title="Test" size={32} />)
    const el = container.firstChild as HTMLElement
    expect(el.style.width).toBe('32px')
    expect(el.style.height).toBe('32px')
  })

  it('applies deterministic background color', () => {
    const { container: c1 } = render(<ChatAvatar title="Same" />)
    const { container: c2 } = render(<ChatAvatar title="Same" />)
    const bg1 = (c1.firstChild as HTMLElement).style.backgroundColor
    const bg2 = (c2.firstChild as HTMLElement).style.backgroundColor
    expect(bg1).toBe(bg2)
  })
})
