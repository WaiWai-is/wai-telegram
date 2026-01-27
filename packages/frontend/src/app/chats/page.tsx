'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { format } from 'date-fns'
import { api, Chat } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function ChatsPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data, isLoading, error } = useQuery({
    queryKey: ['chats'],
    queryFn: () => api.getChats(),
    enabled: !!user,
  })

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshChats(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chats'] })
    },
  })

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  const getChatTypeIcon = (type: Chat['chat_type']) => {
    switch (type) {
      case 'private':
        return '👤'
      case 'group':
        return '👥'
      case 'supergroup':
        return '👥'
      case 'channel':
        return '📢'
      default:
        return '💬'
    }
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/" className="text-sm text-blue-600 hover:underline mb-2 block">
              ← Back to Dashboard
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Your Chats
            </h1>
          </div>
          <button
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
          >
            {refreshMutation.isPending ? 'Refreshing...' : 'Refresh from Telegram'}
          </button>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        ) : error ? (
          <div className="p-4 bg-red-100 text-red-700 rounded-lg">
            Failed to load chats. Make sure you&apos;ve connected your Telegram account.
          </div>
        ) : !data?.chats.length ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            <p className="mb-4">No chats synced yet.</p>
            <Link
              href="/settings"
              className="text-blue-600 hover:underline"
            >
              Connect your Telegram account to get started
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {data.chats.map((chat) => (
              <Link
                key={chat.id}
                href={`/chats/${chat.id}`}
                className="block p-4 bg-white dark:bg-gray-800 rounded-lg hover:shadow-md transition"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{getChatTypeIcon(chat.chat_type)}</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 dark:text-white truncate">
                      {chat.title}
                    </h3>
                    <div className="flex gap-4 text-sm text-gray-500 dark:text-gray-400">
                      <span>{chat.total_messages_synced} messages</span>
                      {chat.last_sync_at && (
                        <span>
                          Synced {format(new Date(chat.last_sync_at), 'MMM d, h:mm a')}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-gray-400">→</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
