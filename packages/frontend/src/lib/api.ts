const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? '').trim()

class ApiClient {
  private accessToken: string | null = null
  private refreshToken: string | null = null
  private onTokenRefresh: ((accessToken: string, refreshToken: string) => void) | null = null
  private onAuthFailure: (() => void) | null = null
  private refreshPromise: Promise<boolean> | null = null

  setAccessToken(token: string | null) {
    this.accessToken = token
  }

  setRefreshToken(token: string | null) {
    this.refreshToken = token
  }

  setTokenRefreshCallback(cb: (accessToken: string, refreshToken: string) => void) {
    this.onTokenRefresh = cb
  }

  setAuthFailureCallback(cb: () => void) {
    this.onAuthFailure = cb
  }

  private getBaseUrl() {
    if (API_URL) return API_URL
    if (typeof window !== 'undefined') return window.location.origin
    return 'http://localhost:3000'
  }

  private async attemptTokenRefresh(): Promise<boolean> {
    if (!this.refreshToken) return false

    // Deduplicate concurrent refresh attempts
    if (this.refreshPromise) return this.refreshPromise

    this.refreshPromise = (async () => {
      try {
        const response = await fetch(new URL('/api/v1/auth/refresh', this.getBaseUrl()).toString(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        })

        if (!response.ok) return false

        const tokens = await response.json()
        this.accessToken = tokens.access_token
        this.refreshToken = tokens.refresh_token
        this.onTokenRefresh?.(tokens.access_token, tokens.refresh_token)
        return true
      } catch {
        return false
      } finally {
        this.refreshPromise = null
      }
    })()

    return this.refreshPromise
  }

  private async request<T>(
    method: string,
    path: string,
    options: { body?: unknown; params?: Record<string, string> } = {}
  ): Promise<T> {
    const url = new URL(path, this.getBaseUrl())
    if (options.params) {
      Object.entries(options.params).forEach(([key, value]) => {
        url.searchParams.append(key, value)
      })
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`
    }

    let response = await fetch(url.toString(), {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    })

    // 401 interceptor: try token refresh once, then retry
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.attemptTokenRefresh()
      if (refreshed) {
        headers['Authorization'] = `Bearer ${this.accessToken}`
        response = await fetch(url.toString(), {
          method,
          headers,
          body: options.body ? JSON.stringify(options.body) : undefined,
        })
      } else {
        this.onAuthFailure?.()
      }
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }))
      throw new Error(error.detail || 'Request failed')
    }

    return response.json()
  }

  // Auth
  async login(email: string, password: string) {
    const formData = new URLSearchParams()
    formData.append('username', email)
    formData.append('password', password)

    const response = await fetch(new URL('/api/v1/auth/login', this.getBaseUrl()).toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(error.detail || 'Login failed')
    }

    return response.json()
  }

  async register(email: string, password: string) {
    return this.request<{ access_token: string; refresh_token: string }>(
      'POST',
      '/api/v1/auth/register',
      { body: { email, password } }
    )
  }

  async getMe() {
    return this.request<{ id: string; email: string; has_api_key: boolean }>(
      'GET',
      '/api/v1/auth/me'
    )
  }

  async generateApiKey() {
    return this.request<{ api_key: string }>('POST', '/api/v1/auth/api-key')
  }

  // Telegram
  async requestCode(phone_number: string) {
    return this.request<{ phone_code_hash: string; code_type: string }>(
      'POST',
      '/api/v1/telegram/request-code',
      { body: { phone_number } }
    )
  }

  async verifyCode(
    phone_number: string,
    phone_code_hash: string,
    code: string,
    password?: string
  ) {
    return this.request<{ success: boolean; telegram_user_id: number }>(
      'POST',
      '/api/v1/telegram/verify-code',
      { body: { phone_number, phone_code_hash, code, password } }
    )
  }

  async getTelegramSession() {
    return this.request<{ id: string; phone_number: string; is_active: boolean } | null>(
      'GET',
      '/api/v1/telegram/session'
    )
  }

  async deleteTelegramSession() {
    return this.request<{ message: string }>('DELETE', '/api/v1/telegram/session')
  }

  // Chats
  async getChats(chatType?: string, limit = 100, cursor?: string) {
    const params: Record<string, string> = {}
    if (chatType) params.chat_type = chatType
    params.limit = String(limit)
    if (cursor) params.cursor = cursor
    return this.request<ChatListPage>(
      'GET',
      '/api/v1/chats',
      { params }
    )
  }

  async refreshChats() {
    return this.request<ChatListPage>(
      'POST',
      '/api/v1/chats/refresh'
    )
  }

  async getChatMessages(chatId: string, limit = 50, before?: string) {
    const params: Record<string, string> = { limit: String(limit) }
    if (before) params.before = before
    return this.request<MessageListPage>(
      'GET',
      `/api/v1/chats/${chatId}/messages`,
      { params }
    )
  }

  // Sync
  async syncChat(chatId: string, limit?: number) {
    const params: Record<string, string> = {}
    if (limit !== undefined) params.limit = String(limit)
    return this.request<SyncJob>('POST', `/api/v1/sync/chats/${chatId}`, { params })
  }

  async syncAll(limitPerChat = 500) {
    return this.request<SyncJob>('POST', '/api/v1/sync/all', {
      params: { limit_per_chat: String(limitPerChat) },
    })
  }

  async getSyncJob(jobId: string) {
    return this.request<SyncJobProgress>('GET', `/api/v1/sync/jobs/${jobId}`)
  }

  async getSyncJobs(limit = 20) {
    return this.request<SyncJob[]>('GET', '/api/v1/sync/jobs', {
      params: { limit: String(limit) },
    })
  }

  // Search
  async search(query: string, chatIds?: string[], limit = 20) {
    return this.request<{ results: SearchResult[]; total: number }>(
      'POST',
      '/api/v1/search',
      { body: { query, chat_ids: chatIds, limit } }
    )
  }

  // Digests
  async getDigests(limit = 30) {
    return this.request<Digest[]>('GET', '/api/v1/digests', {
      params: { limit: String(limit) },
    })
  }

  async generateDigest(date?: string) {
    return this.request<Digest>('POST', '/api/v1/digests/generate', {
      body: date ? { date } : {},
    })
  }

  // Settings
  async getSettings() {
    return this.request<UserSettings>('GET', '/api/v1/settings')
  }

  async updateSettings(settings: Partial<UserSettingsUpdate>) {
    return this.request<UserSettings>('PUT', '/api/v1/settings', {
      body: settings,
    })
  }

  async testBot() {
    return this.request<{ success: boolean; message: string }>(
      'POST',
      '/api/v1/settings/test-bot'
    )
  }
}

export const api = new ApiClient()

// Types
export interface Chat {
  id: string
  telegram_chat_id: number
  chat_type: 'private' | 'group' | 'supergroup' | 'channel'
  title: string
  username: string | null
  last_sync_at: string | null
  last_activity_at: string | null
  total_messages_synced: number
  last_message_text: string | null
  last_message_sender_name: string | null
  unread_count: number
}

export interface Message {
  id: string
  telegram_message_id: number
  text: string | null
  has_media: boolean
  media_type: string | null
  sender_id: number | null
  sender_name: string | null
  is_outgoing: boolean
  sent_at: string
}

export interface SearchResult {
  id: string
  chat_id: string
  chat_title: string
  text: string | null
  sender_name: string | null
  is_outgoing: boolean
  sent_at: string
  similarity: number
}

export interface ChatListPage {
  chats: Chat[]
  has_more: boolean
  next_cursor: string | null
  total: number | null
}

export interface MessageListPage {
  messages: Message[]
  total: number | null
  has_more: boolean
  next_cursor: string | null
}

export interface SyncJob {
  id: string
  chat_id: string | null
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
  messages_processed: number
  error_message?: string | null
}

export interface SyncJobProgress {
  job_id: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
  messages_processed: number
  current_chat: string | null
  progress_percent: number | null
  error_message: string | null
  retry_after_seconds: number | null
  chats_completed: number | null
  total_chats: number | null
}

export interface Digest {
  id: string
  digest_date: string
  content: string
  summary_stats: Record<string, unknown>
}

export interface UserSettings {
  digest_enabled: boolean
  digest_hour_utc: number
  digest_timezone: string
  digest_telegram_enabled: boolean
  realtime_sync_enabled: boolean
  listener_active: boolean
}

export interface UserSettingsUpdate {
  digest_enabled?: boolean
  digest_hour_utc?: number
  digest_timezone?: string
  digest_telegram_enabled?: boolean
  realtime_sync_enabled?: boolean
}
