'use client'

import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api, UserSettings, UserSettingsUpdate, ApiKeyInfo, ApiKeyCreateResponse } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useRouter } from 'next/navigation'

// --- Timezone conversion utilities ---

function getTimezoneOffsetHours(tz: string): number {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    timeZoneName: 'shortOffset',
  })
  const parts = formatter.formatToParts(new Date())
  const tzPart = parts.find((p) => p.type === 'timeZoneName')?.value ?? 'GMT'
  // tzPart is like "GMT", "GMT+5", "GMT-4", "GMT+5:30"
  if (tzPart === 'GMT' || tzPart === 'UTC') return 0
  const match = tzPart.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/)
  if (!match) return 0
  const sign = match[1] === '+' ? 1 : -1
  const hours = parseInt(match[2], 10)
  const minutes = parseInt(match[3] || '0', 10)
  return sign * (hours + minutes / 60)
}

function localHourToUtc(localHour: number, tz: string): number {
  const offset = getTimezoneOffsetHours(tz)
  return ((localHour - offset) % 24 + 24) % 24
}

function utcHourToLocal(utcHour: number, tz: string): number {
  const offset = getTimezoneOffsetHours(tz)
  return ((utcHour + offset) % 24 + 24) % 24
}

function formatHour(hour: number): string {
  return `${String(Math.floor(hour)).padStart(2, '0')}:00`
}

function detectTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

function getTimezoneLabel(tz: string): string {
  const offset = getTimezoneOffsetHours(tz)
  const sign = offset >= 0 ? '+' : '-'
  const absOffset = Math.abs(offset)
  const h = Math.floor(absOffset)
  const m = Math.round((absOffset - h) * 60)
  const offsetStr = m > 0 ? `${h}:${String(m).padStart(2, '0')}` : `${h}`
  const city = tz.split('/').pop()!.replace(/_/g, ' ')
  return `(UTC${sign}${offsetStr}) ${city}`
}

interface TimezoneOption {
  value: string
  label: string
  region: string
}

function buildTimezoneList(): TimezoneOption[] {
  const zones = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []
  return zones
    .filter((tz) => tz.includes('/'))
    .map((tz) => ({
      value: tz,
      label: getTimezoneLabel(tz),
      region: tz.split('/')[0],
    }))
}

// --- TimezonePicker component ---

function TimezonePicker({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (tz: string) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const allTimezones = useMemo(() => buildTimezoneList(), [])

  const filtered = useMemo(() => {
    if (!search) return allTimezones
    const q = search.toLowerCase()
    return allTimezones.filter(
      (tz) => tz.label.toLowerCase().includes(q) || tz.value.toLowerCase().includes(q)
    )
  }, [allTimezones, search])

  const grouped = useMemo(() => {
    const groups: Record<string, TimezoneOption[]> = {}
    for (const tz of filtered) {
      if (!groups[tz.region]) groups[tz.region] = []
      groups[tz.region].push(tz)
    }
    return groups
  }, [filtered])

  useEffect(() => {
    if (!open) return
    searchRef.current?.focus()
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2.5 border rounded-lg bg-transparent text-primary text-left text-sm focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 flex items-center justify-between"
      >
        <span>{getTimezoneLabel(value)}</span>
        <svg className={`w-4 h-4 text-tertiary transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-surface border rounded-lg shadow-lg max-h-72 overflow-hidden flex flex-col">
          <div className="p-2 border-b">
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search timezone..."
              className="w-full px-2 py-1.5 text-sm border rounded bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <div className="overflow-y-auto">
            {Object.entries(grouped).map(([region, tzs]) => (
              <div key={region}>
                <div className="px-3 py-1.5 text-xs font-medium text-tertiary uppercase tracking-wider bg-surface-hover sticky top-0">
                  {region}
                </div>
                {tzs.map((tz) => (
                  <button
                    key={tz.value}
                    type="button"
                    onClick={() => {
                      onChange(tz.value)
                      setOpen(false)
                      setSearch('')
                    }}
                    className={`w-full px-3 py-2 text-sm text-left hover:bg-surface-hover transition-colors ${
                      tz.value === value ? 'text-primary font-medium' : 'text-secondary'
                    }`}
                  >
                    {tz.label}
                  </button>
                ))}
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="px-3 py-4 text-sm text-tertiary text-center">No timezones found</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

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

// --- MCP Platform Configs ---

interface PlatformConfig {
  id: string
  name: string
  filePath: string
  getConfig: (apiKey: string) => string
}

const PLATFORM_CONFIGS: PlatformConfig[] = [
  {
    id: 'claude-ai',
    name: 'Claude.ai',
    filePath: 'Settings → Connectors → Add custom connector',
    getConfig: (apiKey) =>
      `Name: Telegram WAI\nRemote MCP server URL:\nhttps://telegram.waiwai.is/mcp/sse?key=${apiKey}`,
  },
  {
    id: 'claude-desktop',
    name: 'Claude Desktop',
    filePath: '~/Library/Application Support/Claude/claude_desktop_config.json',
    getConfig: (apiKey) => JSON.stringify({
      mcpServers: {
        'telegram-wai': {
          command: 'uvx',
          args: ['--from', 'telegram-wai-mcp', 'telegram-wai-mcp'],
          env: {
            TELEGRAM_AI_URL: 'https://telegram.waiwai.is',
            TELEGRAM_AI_KEY: apiKey,
          },
        },
      },
    }, null, 2),
  },
  {
    id: 'claude-code',
    name: 'Claude Code',
    filePath: 'Run in terminal',
    getConfig: (apiKey) =>
      `claude mcp add telegram-wai -e TELEGRAM_AI_URL=https://telegram.waiwai.is -e TELEGRAM_AI_KEY=${apiKey} -- uvx --from telegram-wai-mcp telegram-wai-mcp`,
  },
  {
    id: 'cursor',
    name: 'Cursor',
    filePath: '.cursor/mcp.json',
    getConfig: (apiKey) => JSON.stringify({
      mcpServers: {
        'telegram-wai': {
          command: 'uvx',
          args: ['--from', 'telegram-wai-mcp', 'telegram-wai-mcp'],
          env: {
            TELEGRAM_AI_URL: 'https://telegram.waiwai.is',
            TELEGRAM_AI_KEY: apiKey,
          },
        },
      },
    }, null, 2),
  },
  {
    id: 'windsurf',
    name: 'Windsurf',
    filePath: '~/.codeium/windsurf/mcp_config.json',
    getConfig: (apiKey) => JSON.stringify({
      mcpServers: {
        'telegram-wai': {
          command: 'uvx',
          args: ['--from', 'telegram-wai-mcp', 'telegram-wai-mcp'],
          env: {
            TELEGRAM_AI_URL: 'https://telegram.waiwai.is',
            TELEGRAM_AI_KEY: apiKey,
          },
        },
      },
    }, null, 2),
  },
  {
    id: 'cline',
    name: 'Cline',
    filePath: 'Cline MCP settings in VS Code',
    getConfig: (apiKey) => JSON.stringify({
      mcpServers: {
        'telegram-wai': {
          command: 'uvx',
          args: ['--from', 'telegram-wai-mcp', 'telegram-wai-mcp'],
          env: {
            TELEGRAM_AI_URL: 'https://telegram.waiwai.is',
            TELEGRAM_AI_KEY: apiKey,
          },
        },
      },
    }, null, 2),
  },
]

function PlatformAccordion({ selectedApiKey }: { selectedApiKey: string }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const handleCopy = async (id: string, text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  const displayKey = selectedApiKey || 'YOUR_API_KEY'

  return (
    <div className="space-y-1">
      {PLATFORM_CONFIGS.map((platform) => {
        const isOpen = openId === platform.id
        const config = platform.getConfig(displayKey)
        return (
          <div key={platform.id} className="border rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setOpenId(isOpen ? null : platform.id)}
              className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-surface-hover transition-colors"
            >
              <span className="text-sm font-medium text-primary">{platform.name}</span>
              <svg
                className={`w-4 h-4 text-tertiary transition-transform ${isOpen ? 'rotate-180' : ''}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {isOpen && (
              <div className="px-4 pb-4 border-t">
                <p className="text-xs text-tertiary mt-3 mb-2">{platform.filePath}</p>
                <pre className="text-xs overflow-x-auto bg-surface-hover rounded-lg p-3 text-primary">{config}</pre>
                <button
                  type="button"
                  onClick={() => handleCopy(platform.id, config)}
                  className="mt-2 px-3 py-1.5 text-xs border rounded-lg text-secondary hover:bg-surface-hover transition-colors"
                >
                  {copied === platform.id ? 'Copied!' : 'Copy to Clipboard'}
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
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
  const [newKeyName, setNewKeyName] = useState('')
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<ApiKeyCreateResponse | null>(null)
  const [selectedKeyForConfig, setSelectedKeyForConfig] = useState('')
  const [keyCopied, setKeyCopied] = useState(false)

  // Test connection state
  const [testStatus, setTestStatus] = useState<{ success?: boolean; message?: string; chat_count?: number; message_count?: number } | null>(null)

  // Bot test state
  const [testBotStatus, setTestBotStatus] = useState<{ success?: boolean; message?: string } | null>(null)

  // Timezone auto-detection
  const [detectedTimezone, setDetectedTimezone] = useState<string | null>(null)

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

  const { data: apiKeys, isLoading: keysLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => api.listApiKeys(),
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

  const createKeyMutation = useMutation({
    mutationFn: (name: string) => api.createApiKey(name),
    onSuccess: (data) => {
      setNewlyCreatedKey(data)
      setNewKeyName('')
      setSelectedKeyForConfig(data.api_key)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const revokeKeyMutation = useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const toggleKeyMutation = useMutation({
    mutationFn: ({ keyId, isActive }: { keyId: string; isActive: boolean }) =>
      api.toggleApiKey(keyId, isActive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const testConnectionMutation = useMutation({
    mutationFn: () => api.testMcpConnection(),
    onSuccess: (data) => setTestStatus(data),
    onError: (err: Error) => setTestStatus({ success: false, message: err.message }),
  })

  // Auto-detect timezone on first visit
  useEffect(() => {
    if (settings && settings.digest_timezone === 'UTC') {
      const browserTz = detectTimezone()
      if (browserTz && browserTz !== 'UTC') {
        setDetectedTimezone(browserTz)
      }
    }
  }, [settings])

  const handleAcceptTimezone = useCallback(() => {
    if (!detectedTimezone || !settings) return
    // Keep the same local time by recalculating UTC hour
    const currentLocalHour = utcHourToLocal(settings.digest_hour_utc, 'UTC')
    const newUtcHour = localHourToUtc(currentLocalHour, detectedTimezone)
    updateSettingsMutation.mutate({
      digest_timezone: detectedTimezone,
      digest_hour_utc: Math.round(newUtcHour) % 24,
    })
    setDetectedTimezone(null)
  }, [detectedTimezone, settings, updateSettingsMutation])

  const handleTimezoneChange = useCallback((tz: string) => {
    if (!settings) return
    // Keep the same local time, recalculate UTC hour
    const currentLocalHour = utcHourToLocal(settings.digest_hour_utc, settings.digest_timezone)
    const newUtcHour = localHourToUtc(currentLocalHour, tz)
    updateSettingsMutation.mutate({
      digest_timezone: tz,
      digest_hour_utc: Math.round(newUtcHour) % 24,
    })
    setDetectedTimezone(null)
  }, [settings, updateSettingsMutation])

  const handleDigestTimeChange = useCallback((timeValue: string) => {
    if (!settings) return
    const localHour = parseInt(timeValue.split(':')[0], 10)
    if (isNaN(localHour)) return
    const utcHour = localHourToUtc(localHour, settings.digest_timezone)
    updateSettingsMutation.mutate({ digest_hour_utc: Math.round(utcHour) % 24 })
  }, [settings, updateSettingsMutation])

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
                  {detectedTimezone && (
                    <div className="flex items-center justify-between gap-3 p-3 border rounded-lg bg-surface-hover">
                      <p className="text-sm text-secondary">
                        Detected timezone: <span className="font-medium text-primary">{getTimezoneLabel(detectedTimezone)}</span>
                      </p>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          type="button"
                          onClick={handleAcceptTimezone}
                          disabled={updateSettingsMutation.isPending}
                          className="px-3 py-1.5 text-sm bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
                        >
                          Use this
                        </button>
                        <button
                          type="button"
                          onClick={() => setDetectedTimezone(null)}
                          className="px-3 py-1.5 text-sm border text-secondary rounded-lg hover:bg-surface-hover transition-colors"
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-secondary">
                      Timezone
                    </label>
                    <TimezonePicker
                      value={settings.digest_timezone}
                      onChange={handleTimezoneChange}
                      disabled={updateSettingsMutation.isPending}
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-secondary">
                      Digest time
                    </label>
                    <div className="flex items-center gap-3">
                      <input
                        type="time"
                        value={formatHour(utcHourToLocal(settings.digest_hour_utc, settings.digest_timezone))}
                        onChange={(e) => handleDigestTimeChange(e.target.value)}
                        step="3600"
                        disabled={updateSettingsMutation.isPending}
                        className="px-3 py-2.5 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                      <span className="text-sm text-tertiary">
                        {formatHour(utcHourToLocal(settings.digest_hour_utc, settings.digest_timezone))} {settings.digest_timezone.split('/').pop()?.replace(/_/g, ' ')}
                      </span>
                    </div>
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
                    <div className="p-4 border rounded-lg space-y-3">
                      <p className="text-sm font-medium text-primary">Setup</p>
                      <ol className="text-sm text-secondary space-y-1 list-decimal list-inside">
                        <li>Open <a href="https://t.me/wai_telegram_bot" target="_blank" rel="noopener noreferrer" className="underline text-primary hover:opacity-80">@wai_telegram_bot</a> in Telegram</li>
                        <li>Press <strong>Start</strong> to allow the bot to message you</li>
                        <li>Send a test below to confirm it works</li>
                      </ol>
                      <div className="flex items-center gap-3 pt-1">
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
                    </div>
                  )}
                </>
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

        {/* API Keys */}
        <section className="border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-medium mb-4 text-primary">
            API Keys
          </h2>
          <p className="text-sm text-secondary mb-4">
            Create API keys to connect MCP clients like Claude Desktop, Claude Code, Cursor, and more.
          </p>

          {/* Existing keys table */}
          {keysLoading ? (
            <div className="animate-pulse h-20 bg-surface-hover rounded mb-4" />
          ) : apiKeys && apiKeys.length > 0 ? (
            <div className="border rounded-lg overflow-hidden mb-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface-hover">
                    <th className="text-left px-4 py-2.5 font-medium text-secondary">Name</th>
                    <th className="text-left px-4 py-2.5 font-medium text-secondary">Key</th>
                    <th className="text-left px-4 py-2.5 font-medium text-secondary">Status</th>
                    <th className="text-left px-4 py-2.5 font-medium text-secondary">Expires</th>
                    <th className="text-right px-4 py-2.5 font-medium text-secondary">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((key) => {
                    const isExpired = key.expires_at && new Date(key.expires_at) < new Date()
                    return (
                    <tr key={key.id} className="border-t">
                      <td className="px-4 py-2.5 text-primary">{key.name}</td>
                      <td className="px-4 py-2.5">
                        <code className="text-xs text-tertiary">{key.key_hint}</code>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          isExpired
                            ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                            : key.is_active
                            ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                        }`}>
                          {isExpired ? 'Expired' : key.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-tertiary">
                        {key.expires_at
                          ? new Date(key.expires_at).toLocaleDateString()
                          : 'Never'}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => toggleKeyMutation.mutate({ keyId: key.id, isActive: !key.is_active })}
                            disabled={toggleKeyMutation.isPending}
                            className="p-1.5 rounded hover:bg-surface-hover transition-colors text-tertiary hover:text-primary"
                            title={key.is_active ? 'Disable' : 'Enable'}
                          >
                            {key.is_active ? (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                              </svg>
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (confirm(`Revoke API key "${key.name}"? This cannot be undone.`)) {
                                revokeKeyMutation.mutate(key.id)
                              }
                            }}
                            disabled={revokeKeyMutation.isPending}
                            className="p-1.5 rounded hover:bg-surface-hover transition-colors text-tertiary hover:text-red-500"
                            title="Revoke"
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-tertiary mb-4">No API keys yet. Create one to get started.</p>
          )}

          {/* Newly created key display */}
          {newlyCreatedKey && (
            <div className="p-4 border border-green-300 dark:border-green-700 rounded-lg mb-4 bg-green-50 dark:bg-green-900/10">
              <p className="text-sm font-medium text-primary mb-2">
                API key &quot;{newlyCreatedKey.name}&quot; created successfully
              </p>
              <p className="text-sm text-secondary mb-2">
                Copy this key now. It won&apos;t be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 p-2 bg-surface-hover rounded text-sm break-all text-primary">
                  {newlyCreatedKey.api_key}
                </code>
                <button
                  type="button"
                  onClick={async () => {
                    await navigator.clipboard.writeText(newlyCreatedKey.api_key)
                    setKeyCopied(true)
                    setTimeout(() => setKeyCopied(false), 2000)
                  }}
                  className="shrink-0 px-3 py-2 text-sm border rounded-lg hover:bg-surface-hover transition-colors text-secondary"
                >
                  {keyCopied ? 'Copied!' : 'Copy'}
                </button>
              </div>
            </div>
          )}

          {/* Create new key form */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="Key name (e.g. Claude Desktop)"
              className="flex-1 px-3 py-2.5 border rounded-lg bg-transparent text-primary text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              type="button"
              onClick={() => {
                if (newKeyName.trim()) {
                  setNewlyCreatedKey(null)
                  createKeyMutation.mutate(newKeyName.trim())
                }
              }}
              disabled={createKeyMutation.isPending || !newKeyName.trim()}
              className="shrink-0 px-4 py-2.5 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity text-sm"
            >
              {createKeyMutation.isPending ? 'Creating...' : 'Create Key'}
            </button>
          </div>

          {/* Test connection */}
          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setTestStatus(null)
                testConnectionMutation.mutate()
              }}
              disabled={testConnectionMutation.isPending}
              className="px-4 py-2 border text-primary rounded-lg hover:bg-surface-hover transition-colors disabled:opacity-50 text-sm"
            >
              {testConnectionMutation.isPending ? 'Testing...' : 'Test MCP Connection'}
            </button>
            {testStatus && (
              <p className={`text-sm ${testStatus.success ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {testStatus.message}
                {testStatus.chat_count !== undefined && ` (${testStatus.chat_count} chats, ${testStatus.message_count} messages)`}
              </p>
            )}
          </div>
        </section>

        {/* MCP Setup Instructions */}
        <section className="border rounded-xl p-6">
          <h2 className="text-lg font-medium mb-2 text-primary">
            MCP Setup
          </h2>
          <p className="text-sm text-secondary mb-4">
            Configure your MCP client to connect to WAI Telegram. Select a platform below for setup instructions.
          </p>

          <PlatformAccordion selectedApiKey={selectedKeyForConfig || newlyCreatedKey?.api_key || ''} />
        </section>
      </div>
    </main>
  )
}
