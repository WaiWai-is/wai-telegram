'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
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
      if (err.message.includes('password')) {
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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-2xl mx-auto">
        <Link href="/" className="text-sm text-blue-600 hover:underline mb-2 block">
          ← Back to Dashboard
        </Link>
        <h1 className="text-2xl font-bold mb-8 text-gray-900 dark:text-white">
          Settings
        </h1>

        {/* Telegram Connection */}
        <section className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm mb-6">
          <h2 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">
            Telegram Connection
          </h2>

          {sessionLoading ? (
            <div className="animate-pulse h-20 bg-gray-100 dark:bg-gray-700 rounded" />
          ) : session?.is_active ? (
            <div>
              <div className="flex items-center gap-3 mb-4">
                <span className="w-3 h-3 bg-green-500 rounded-full" />
                <span className="text-gray-700 dark:text-gray-300">
                  Connected as {session.phone_number}
                </span>
              </div>
              <button
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
                className="px-4 py-2 text-red-600 border border-red-600 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition"
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
                <div className="p-3 bg-red-100 text-red-700 rounded-lg text-sm">
                  {authError}
                </div>
              )}

              {authStep === 'phone' && (
                <div>
                  <label className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                    Phone Number
                  </label>
                  <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+1234567890"
                    className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white"
                    required
                  />
                </div>
              )}

              {authStep === 'code' && (
                <div>
                  <label className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                    Verification Code
                  </label>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="12345"
                    className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white"
                    required
                  />
                </div>
              )}

              {authStep === 'password' && (
                <div>
                  <label className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                    Two-Factor Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white"
                    required
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={requestCodeMutation.isPending || verifyCodeMutation.isPending}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
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
        <section className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm">
          <h2 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">
            MCP API Key
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            Generate an API key to use with Claude Code MCP integration.
          </p>

          {apiKey ? (
            <div className="space-y-4">
              <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg">
                <p className="text-sm text-yellow-800 dark:text-yellow-200 mb-2">
                  Copy this key now. It won&apos;t be shown again.
                </p>
                <code className="block p-2 bg-white dark:bg-gray-900 rounded text-sm break-all">
                  {apiKey}
                </code>
              </div>
              <div className="p-3 bg-gray-50 dark:bg-gray-900 rounded-lg">
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                  Add this to your Claude Code settings:
                </p>
                <pre className="text-xs overflow-x-auto">
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
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {generateApiKeyMutation.isPending ? 'Generating...' : 'Generate API Key'}
            </button>
          )}

          {user.has_api_key && !apiKey && (
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              You already have an API key. Generating a new one will replace it.
            </p>
          )}
        </section>
      </div>
    </main>
  )
}
