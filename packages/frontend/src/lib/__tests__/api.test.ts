import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fetch globally for API client tests
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

// Helper to create mock responses
function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// Import the api singleton after stubbing fetch
import { api } from '../api'

beforeEach(() => {
  mockFetch.mockReset()
  api.setAccessToken(null)
  api.setRefreshToken(null)
})

describe('ApiClient', () => {
  describe('login', () => {
    it('sends form-urlencoded credentials and returns tokens', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          access_token: 'test-access-token',
          refresh_token: 'test-refresh-token',
          token_type: 'bearer',
        })
      )

      const result = await api.login('test@example.com', 'password123')
      expect(result.access_token).toBe('test-access-token')
      expect(result.refresh_token).toBe('test-refresh-token')

      // Verify it sent form-urlencoded
      const call = mockFetch.mock.calls[0]
      expect(call[1].method).toBe('POST')
      expect(call[1].headers['Content-Type']).toBe('application/x-www-form-urlencoded')
    })

    it('throws on invalid credentials', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ detail: 'Invalid email or password' }, 401)
      )

      await expect(api.login('test@example.com', 'wrong')).rejects.toThrow(
        'Invalid email or password'
      )
    })
  })

  describe('register', () => {
    it('sends JSON body and returns tokens', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          access_token: 'test-access-token',
          refresh_token: 'test-refresh-token',
        })
      )

      const result = await api.register('new@example.com', 'Password1')
      expect(result.access_token).toBe('test-access-token')
    })
  })

  describe('getMe', () => {
    it('returns user info when authenticated', async () => {
      api.setAccessToken('test-token')
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ id: 'user-1', email: 'test@example.com' })
      )

      const user = await api.getMe()
      expect(user.email).toBe('test@example.com')

      // Verify auth header
      const call = mockFetch.mock.calls[0]
      expect(call[1].headers['Authorization']).toBe('Bearer test-token')
    })
  })

  describe('getChats', () => {
    it('returns chat list page', async () => {
      api.setAccessToken('test-token')
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          chats: [{ id: 'chat-1', title: 'John Doe' }],
          has_more: false,
          next_cursor: null,
          total: 1,
        })
      )

      const result = await api.getChats()
      expect(result.chats).toHaveLength(1)
      expect(result.chats[0].title).toBe('John Doe')
    })
  })

  describe('search', () => {
    it('posts query and returns results', async () => {
      api.setAccessToken('test-token')
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          results: [{ id: 'msg-1', similarity: 0.95 }],
          total: 1,
        })
      )

      const result = await api.search('hello')
      expect(result.results).toHaveLength(1)
      expect(result.results[0].similarity).toBe(0.95)
    })
  })

  describe('token refresh on 401', () => {
    it('retries request after successful refresh', async () => {
      api.setAccessToken('expired-token')
      api.setRefreshToken('valid-refresh')

      // First call: 401
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ detail: 'Unauthorized' }, 401)
      )
      // Refresh call: success
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
        })
      )
      // Retry call: success
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ id: 'refreshed-user', email: 'test@example.com' })
      )

      const user = await api.getMe()
      expect(user.id).toBe('refreshed-user')
      expect(mockFetch).toHaveBeenCalledTimes(3)
    })

    it('calls auth failure callback when refresh fails', async () => {
      api.setAccessToken('expired-token')
      api.setRefreshToken('bad-refresh')
      const onFailure = vi.fn()
      api.setAuthFailureCallback(onFailure)

      // First call: 401
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ detail: 'Unauthorized' }, 401)
      )
      // Refresh call: fails
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ detail: 'Invalid' }, 401)
      )

      await expect(api.getMe()).rejects.toThrow()
      expect(onFailure).toHaveBeenCalled()
    })
  })
})
