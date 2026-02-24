'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function SettingsPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()

  // Telegram auth state
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [phoneCodeHash, setPhoneCodeHash] = useState('')
  const [codeType, setCodeType] = useState('')
  const [authStep, setAuthStep] = useState<'phone' | 'code' | 'password'>('phone')
  const [authError, setAuthError] = useState('')

  // API key state
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data: session, isLoading: sessionLoading } = useQuery({
    queryKey: ['telegram-session'],
    queryFn: () => api.getTelegramSession(),
    enabled: !!user,
  })

  const requestCodeMutation = useMutation({
    mutationFn: () => api.requestCode(phone),
    onSuccess: (data) => {
      setPhoneCodeHash(data.phone_code_hash)
      setCodeType(data.code_type || '')
      setAuthStep('code')
      setAuthError('')
    },
    onError: (err: Error) => setAuthError(err.message),
  })

  const verifyCodeMutation = useMutation({
    mutationFn: () => api.verifyCode(phone, phoneCodeHash, code, password || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telegram-session'] })
      setAuthStep('phone')
      setPhone('')
      setCode('')
      setPassword('')
      setPhoneCodeHash('')
      setAuthError('')
    },
    onError: (err: Error) => {
      if (err.message.toLowerCase().includes('password')) {
        setAuthStep('password')
      }
      setAuthError(err.message)
    },
  })

  const disconnectMutation = useMutation({
    mutationFn: () => api.deleteTelegramSession(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telegram-session'] })
    },
  })

  const generateApiKeyMutation = useMutation({
    mutationFn: () => api.generateApiKey(),
    onSuccess: (data) => {
      setApiKey(data.api_key)
    },
  })

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-2xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <div>
            <Link href="/" className="text-sm text-tertiary hover:text-primary transition-colors mb-2 block">
              &larr; Back to Dashboard
            </Link>
            <h1 className="text-3xl font-light tracking-tight text-primary">
              Settings
            </h1>
          </div>
          <ThemeToggle />
        </div>

        {/* Telegram Connection */}
        <section className="border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            Telegram Connection
          </h2>

          {sessionLoading ? (
            <div className="animate-pulse h-20 bg-surface-hover rounded" />
          ) : session?.is_active ? (
            <div>
              <div className="flex items-center gap-3 mb-4">
                <span className="w-3 h-3 bg-primary rounded-full" />
                <span className="text-secondary">
                  Connected as {session.phone_number}
                </span>
              </div>
              <button
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
                className="px-4 py-2 border text-primary rounded-lg hover:bg-surface-hover transition-colors"
              >
                Disconnect
              </button>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (authStep === 'phone') {
                  requestCodeMutation.mutate()
                } else {
                  verifyCodeMutation.mutate()
                }
              }}
              className="space-y-4"
            >
              {authError && (
                <div className="p-3 border rounded-lg text-sm text-primary">
                  {authError}
                </div>
              )}

              {authStep === 'phone' && (
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-secondary">
                    Phone Number
                  </label>
                  <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+1234567890"
                    className="w-full px-3 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    required
                  />
                </div>
              )}

              {authStep === 'code' && (
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-secondary">
                    Verification Code
                  </label>
                  {codeType && (
                    <p className="text-sm text-tertiary mb-2">
                      {codeType === 'app' && 'Code sent to your Telegram app'}
                      {codeType === 'sms' && 'Code sent via SMS'}
                      {codeType === 'call' && 'You will receive a phone call with the code'}
                      {codeType === 'flash_call' && 'Code is the last digits of the calling number'}
                      {codeType === 'missed_call' && 'Code is the last digits of the calling number'}
                      {codeType === 'email' && 'Code sent to your email'}
                      {codeType === 'fragment_sms' && 'Code sent via Fragment SMS'}
                      {!['app', 'sms', 'call', 'flash_call', 'missed_call', 'email', 'fragment_sms'].includes(codeType) && 'Check your Telegram app or SMS for the code'}
                    </p>
                  )}
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="12345"
                    className="w-full px-3 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    required
                  />
                </div>
              )}

              {authStep === 'password' && (
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-secondary">
                    Two-Factor Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-3 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    required
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={requestCodeMutation.isPending || verifyCodeMutation.isPending}
                className="px-4 py-2 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
              >
                {authStep === 'phone'
                  ? requestCodeMutation.isPending
                    ? 'Sending...'
                    : 'Send Code'
                  : verifyCodeMutation.isPending
                  ? 'Verifying...'
                  : 'Verify'}
              </button>
            </form>
          )}
        </section>

        {/* API Key */}
        <section className="border rounded-xl p-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            MCP API Key
          </h2>
          <p className="text-sm text-secondary mb-4">
            Generate an API key to use with Claude Code MCP integration.
          </p>

          {apiKey ? (
            <div className="space-y-4">
              <div className="p-3 border rounded-lg">
                <p className="text-sm text-secondary mb-2">
                  Copy this key now. It won&apos;t be shown again.
                </p>
                <code className="block p-2 bg-surface-hover rounded text-sm break-all text-primary">
                  {apiKey}
                </code>
              </div>
              <div className="p-3 bg-surface-hover rounded-lg">
                <p className="text-sm text-secondary mb-2">
                  Add this to your Claude Code settings:
                </p>
                <pre className="text-xs overflow-x-auto text-primary">
{`{
  "mcpServers": {
    "telegram-ai": {
      "command": "uvx",
      "args": ["telegram-ai-mcp"],
      "env": {
        "TELEGRAM_AI_URL": "http://localhost:8000",
        "TELEGRAM_AI_KEY": "${apiKey}"
      }
    }
  }
}`}
                </pre>
              </div>
            </div>
          ) : (
            <button
              onClick={() => generateApiKeyMutation.mutate()}
              disabled={generateApiKeyMutation.isPending}
              className="px-4 py-2 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
            >
              {generateApiKeyMutation.isPending ? 'Generating...' : 'Generate API Key'}
            </button>
          )}

          {user.has_api_key && !apiKey && (
            <p className="mt-2 text-sm text-tertiary">
              You already have an API key. Generating a new one will replace it.
            </p>
          )}
        </section>
      </div>
    </main>
  )
}
