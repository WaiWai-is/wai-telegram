'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth'

export default function LoginPage() {
  const router = useRouter()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(email, password)
      router.push('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="flex items-center justify-center min-h-screen p-4">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-light tracking-tight text-center mb-8 text-primary">
          Sign In
        </h1>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="p-3 border rounded-lg text-sm text-primary">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-1.5 text-secondary">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5 text-secondary">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className="text-center mt-6 text-sm text-secondary">
          Don&apos;t have an account?{' '}
          <Link href="/register" className="text-tertiary hover:text-primary transition-colors">
            Create one
          </Link>
        </p>
      </div>
    </main>
  )
}
