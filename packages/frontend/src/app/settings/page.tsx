'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api, UserSettings, UserSettingsUpdate } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

const DIGEST_HOURS = [
  { value: 0, label: 'Midnight (00:00 UTC)' },
  { value: 6, label: 'Morning (06:00 UTC)' },
  { value: 9, label: 'Morning (09:00 UTC)' },
  { value: 12, label: 'Noon (12:00 UTC)' },
  { value: 15, label: 'Afternoon (15:00 UTC)' },
  { value: 18, label: 'Evening (18:00 UTC)' },
  { value: 21, label: 'Night (21:00 UTC)' },
]

const SYNC_INTERVALS = [
  { value: 15, label: 'Every 15 minutes' },
  { value: 60, label: 'Every hour' },
  { value: 360, label: 'Every 6 hours' },
  { value: 720, label: 'Every 12 hours' },
  { value: 1440, label: 'Every 24 hours' },
]

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
        checked ? 'bg-primary' : 'bg-surface-hover'
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-surface shadow ring-0 transition duration-200 ease-in-out ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

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

  // Bot test state
  const [testBotStatus, setTestBotStatus] = useState<{ success?: boolean; message?: string } | null>(null)

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

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['user-settings'],
    queryFn: () => api.getSettings(),
    enabled: !!user,
  })

  const updateSettingsMutation = useMutation({
    mutationFn: (update: Partial<UserSettingsUpdate>) => api.updateSettings(update),
    onSuccess: (data) => {
      queryClient.setQueryData(['user-settings'], data)
    },
  })

  const testBotMutation = useMutation({
    mutationFn: () => api.testBot(),
    onSuccess: (data) => setTestBotStatus(data),
    onError: (err: Error) => setTestBotStatus({ success: false, message: err.message }),
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

  const updateSetting = (key: keyof UserSettingsUpdate, value: unknown) => {
    updateSettingsMutation.mutate({ [key]: value } as Partial<UserSettingsUpdate>)
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

        {/* Digest Settings */}
        <section className="border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            Digest Settings
          </h2>

          {settingsLoading ? (
            <div className="animate-pulse h-32 bg-surface-hover rounded" />
          ) : settings ? (
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-primary">Auto-generate daily digests</p>
                  <p className="text-sm text-tertiary">AI summary of your messages from the previous day</p>
                </div>
                <Toggle
                  checked={settings.digest_enabled}
                  onChange={(v) => updateSetting('digest_enabled', v)}
                  disabled={updateSettingsMutation.isPending}
                />
              </div>

              {settings.digest_enabled && (
                <>
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-secondary">
                      Digest time
                    </label>
                    <select
                      value={settings.digest_hour_utc}
                      onChange={(e) => updateSetting('digest_hour_utc', Number(e.target.value))}
                      disabled={updateSettingsMutation.isPending}
                      className="w-full px-3 py-2.5 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      {DIGEST_HOURS.map((h) => (
                        <option key={h.value} value={h.value}>{h.label}</option>
                      ))}
                    </select>
                  </div>

                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-primary">Send digest via Telegram</p>
                      <p className="text-sm text-tertiary">Receive your daily digest as a Telegram message</p>
                    </div>
                    <Toggle
                      checked={settings.digest_telegram_enabled}
                      onChange={(v) => updateSetting('digest_telegram_enabled', v)}
                      disabled={updateSettingsMutation.isPending}
                    />
                  </div>

                  {settings.digest_telegram_enabled && (
                    <div className="ml-0 p-4 border rounded-lg space-y-3">
                      <p className="text-sm text-secondary">
                        The bot will send digests to your Telegram account directly.
                        Make sure you&apos;ve started a conversation with the bot first.
                      </p>
                      <button
                        onClick={() => {
                          setTestBotStatus(null)
                          testBotMutation.mutate()
                        }}
                        disabled={testBotMutation.isPending}
                        className="px-4 py-2 border text-primary rounded-lg hover:bg-surface-hover transition-colors disabled:opacity-50"
                      >
                        {testBotMutation.isPending ? 'Sending...' : 'Send Test Message'}
                      </button>
                      {testBotStatus && (
                        <p className={`text-sm ${testBotStatus.success ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          {testBotStatus.message}
                        </p>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ) : null}
        </section>

        {/* Auto-sync Settings */}
        <section className="border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            Auto-sync
          </h2>

          {settingsLoading ? (
            <div className="animate-pulse h-24 bg-surface-hover rounded" />
          ) : settings ? (
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-primary">Auto-sync messages</p>
                  <p className="text-sm text-tertiary">Automatically sync new messages at a regular interval</p>
                </div>
                <Toggle
                  checked={settings.auto_sync_enabled}
                  onChange={(v) => updateSetting('auto_sync_enabled', v)}
                  disabled={updateSettingsMutation.isPending}
                />
              </div>

              {settings.auto_sync_enabled && (
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-secondary">
                    Sync interval
                  </label>
                  <select
                    value={settings.auto_sync_interval_minutes}
                    onChange={(e) => updateSetting('auto_sync_interval_minutes', Number(e.target.value))}
                    disabled={updateSettingsMutation.isPending}
                    className="w-full px-3 py-2.5 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    {SYNC_INTERVALS.map((i) => (
                      <option key={i.value} value={i.value}>{i.label}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ) : null}
        </section>

        {/* Real-time Sync */}
        <section className="border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            Real-time Sync
          </h2>

          {settingsLoading ? (
            <div className="animate-pulse h-24 bg-surface-hover rounded" />
          ) : settings ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-primary">Real-time message sync</p>
                  <p className="text-sm text-tertiary">New messages appear automatically as they arrive</p>
                </div>
                <Toggle
                  checked={settings.realtime_sync_enabled}
                  onChange={(v) => updateSetting('realtime_sync_enabled', v)}
                  disabled={updateSettingsMutation.isPending}
                />
              </div>

              {settings.realtime_sync_enabled && (
                <div className="flex items-center gap-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${settings.listener_active ? 'bg-green-500' : 'bg-yellow-500'}`} />
                  <span className="text-sm text-secondary">
                    {settings.listener_active ? 'Listener active' : 'Listener connecting...'}
                  </span>
                </div>
              )}
            </div>
          ) : null}
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
