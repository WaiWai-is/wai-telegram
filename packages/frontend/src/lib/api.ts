const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

class ApiClient {
  private accessToken: string | null = null

  setAccessToken(token: string | null) {
    this.accessToken = token
  }

  private async request<T>(
    method: string,
    path: string,
    options: { body?: unknown; params?: Record<string, string> } = {}
  ): Promise<T> {
    const url = new URL(`${API_URL}${path}`)
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

    const response = await fetch(url.toString(), {
      method,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    })

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

    const response = await fetch(`${API_URL}/api/v1/auth/login`, {
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
    return this.request<{ phone_code_hash: string }>(
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
  async getChats(chatType?: string) {
    const params: Record<string, string> = {}
    if (chatType) params.chat_type = chatType
    return this.request<{ chats: Chat[]; total: number }>(
      'GET',
      '/api/v1/chats',
      { params }
    )
  }

  async refreshChats() {
    return this.request<{ chats: Chat[]; total: number }>(
      'POST',
      '/api/v1/chats/refresh'
    )
  }

  async getChatMessages(chatId: string, limit = 50, offset = 0) {
    return this.request<{ messages: Message[]; total: number; has_more: boolean }>(
      'GET',
      `/api/v1/chats/${chatId}/messages`,
      { params: { limit: String(limit), offset: String(offset) } }
    )
  }

  // Sync
  async syncChat(chatId: string) {
    return this.request<SyncJob>('POST', `/api/v1/sync/chats/${chatId}`)
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
  total_messages_synced: number
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

export interface SyncJob {
  id: string
  chat_id: string | null
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  messages_processed: number
}

export interface Digest {
  id: string
  digest_date: string
  content: string
  summary_stats: Record<string, unknown>
}
