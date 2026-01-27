'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { use } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { MessageList } from '@/components/MessageList'

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data: chatData } = useQuery({
    queryKey: ['chats'],
    queryFn: () => api.getChats(),
    enabled: !!user,
  })

  const chat = chatData?.chats.find((c) => c.id === id)

  const { data: messagesData, isLoading } = useQuery({
    queryKey: ['messages', id],
    queryFn: () => api.getChatMessages(id),
    enabled: !!user && !!id,
  })

  const syncMutation = useMutation({
    mutationFn: () => api.syncChat(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messages', id] })
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

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/chats" className="text-sm text-blue-600 hover:underline mb-2 block">
              ← Back to Chats
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {chat?.title || 'Chat'}
            </h1>
            {chat && (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {chat.total_messages_synced} messages synced
              </p>
            )}
          </div>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
          >
            {syncMutation.isPending ? 'Syncing...' : 'Sync Messages'}
          </button>
        </div>

        {syncMutation.isError && (
          <div className="mb-4 p-3 bg-red-100 text-red-700 rounded-lg">
            Sync failed: {(syncMutation.error as Error).message}
          </div>
        )}

        {syncMutation.isSuccess && (
          <div className="mb-4 p-3 bg-green-100 text-green-700 rounded-lg">
            Synced {syncMutation.data.messages_processed} messages
          </div>
        )}

        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm">
          <MessageList
            messages={messagesData?.messages || []}
            isLoading={isLoading}
          />
        </div>
      </div>
    </main>
  )
}
