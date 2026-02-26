import { http, HttpResponse } from 'msw'

const API_BASE = 'http://test/api/v1'

export const handlers = [
  // Auth
  http.post(`${API_BASE}/auth/login`, async ({ request }) => {
    const body = await request.text()
    const params = new URLSearchParams(body)
    if (params.get('password') === 'wrong') {
      return HttpResponse.json({ detail: 'Invalid email or password' }, { status: 401 })
    }
    return HttpResponse.json({
      access_token: 'test-access-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
    })
  }),

  http.post(`${API_BASE}/auth/register`, async ({ request }) => {
    return HttpResponse.json({
      access_token: 'test-access-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
    })
  }),

  http.post(`${API_BASE}/auth/refresh`, () => {
    return HttpResponse.json({
      access_token: 'new-access-token',
      refresh_token: 'new-refresh-token',
      token_type: 'bearer',
    })
  }),

  http.get(`${API_BASE}/auth/me`, () => {
    return HttpResponse.json({
      id: '123e4567-e89b-12d3-a456-426614174000',
      email: 'test@example.com',
      created_at: '2024-01-01T00:00:00Z',
    })
  }),

  http.get(`${API_BASE}/auth/api-keys`, () => {
    return HttpResponse.json([
      {
        id: 'key-1',
        name: 'Test Key',
        key_hint: 'wai_****abcd',
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
        last_used_at: null,
      },
    ])
  }),

  http.post(`${API_BASE}/auth/api-keys`, async ({ request }) => {
    const body = await request.json() as { name: string }
    return HttpResponse.json({
      id: 'new-key-id',
      name: body.name,
      api_key: 'wai_test_key_12345678901234567890123456',
      key_hint: 'wai_****7890',
      message: 'Store this API key securely.',
    })
  }),

  // Chats
  http.get(`${API_BASE}/chats`, () => {
    return HttpResponse.json({
      chats: [
        {
          id: 'chat-1',
          telegram_chat_id: 12345,
          chat_type: 'private',
          title: 'John Doe',
          username: 'johndoe',
          last_sync_at: '2024-01-01T00:00:00Z',
          last_activity_at: '2024-01-01T12:00:00Z',
          total_messages_synced: 100,
          last_message_text: 'Hello!',
          last_message_sender_name: 'John',
          unread_count: 0,
          created_at: '2024-01-01T00:00:00Z',
        },
      ],
      has_more: false,
      next_cursor: null,
      total: 1,
    })
  }),

  // Search
  http.post(`${API_BASE}/search`, async ({ request }) => {
    const body = await request.json() as { query: string }
    return HttpResponse.json({
      results: [
        {
          id: 'msg-1',
          chat_id: 'chat-1',
          chat_title: 'John Doe',
          text: `Result for: ${body.query}`,
          sender_name: 'John',
          is_outgoing: false,
          sent_at: '2024-01-01T12:00:00Z',
          similarity: 0.95,
          has_media: false,
          media_type: null,
          transcribed_at: null,
        },
      ],
      query: body.query,
      total: 1,
    })
  }),

  // Digests
  http.get(`${API_BASE}/digests`, () => {
    return HttpResponse.json([
      {
        id: 'digest-1',
        digest_date: '2024-01-01',
        content: 'Test digest content',
        summary_stats: { total_messages: 10 },
        created_at: '2024-01-02T09:00:00Z',
      },
    ])
  }),

  http.post(`${API_BASE}/digests/generate`, () => {
    return HttpResponse.json({
      id: 'digest-new',
      digest_date: '2024-01-01',
      content: 'Generated digest',
      summary_stats: { total_messages: 5 },
      created_at: '2024-01-02T09:00:00Z',
    })
  }),

  // Settings
  http.get(`${API_BASE}/settings`, () => {
    return HttpResponse.json({
      digest_enabled: true,
      digest_hour_utc: 9,
      digest_timezone: 'UTC',
      digest_telegram_enabled: false,
      realtime_sync_enabled: false,
      listener_active: false,
    })
  }),

  http.put(`${API_BASE}/settings`, async ({ request }) => {
    const body = await request.json()
    return HttpResponse.json({
      digest_enabled: true,
      digest_hour_utc: 9,
      digest_timezone: 'UTC',
      digest_telegram_enabled: false,
      realtime_sync_enabled: false,
      listener_active: false,
      ...body,
    })
  }),

  // Sync
  http.post(`${API_BASE}/sync/chats/:chatId`, () => {
    return HttpResponse.json({
      id: 'job-1',
      chat_id: 'chat-1',
      status: 'pending',
      messages_processed: 0,
      error_message: null,
      created_at: '2024-01-01T00:00:00Z',
      completed_at: null,
    })
  }),

  http.post(`${API_BASE}/sync/all`, () => {
    return HttpResponse.json({
      id: 'job-2',
      chat_id: null,
      status: 'pending',
      messages_processed: 0,
      error_message: null,
      created_at: '2024-01-01T00:00:00Z',
      completed_at: null,
    })
  }),
]
