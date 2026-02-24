'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { use } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { MessageList } from '@/components/MessageList'
import type { SyncJobProgress } from '@/lib/api'

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [lastSyncResult, setLastSyncResult] = useState<SyncJobProgress | null>(null)

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

  const {
    data: messagesData,
    isLoading,
    isError: isMessagesError,
    error: messagesError,
    refetch: refetchMessages,
  } = useQuery({
    queryKey: ['messages', id],
    queryFn: () => api.getChatMessages(id),
    enabled: !!user && !!id,
  })

  const syncMutation = useMutation({
    mutationFn: (limit?: number) => api.syncChat(id, limit),
    onMutate: () => {
      setLastSyncResult(null)
    },
    onSuccess: (job) => {
      setActiveJobId(job.id)
      queryClient.invalidateQueries({ queryKey: ['sync-jobs'] })
    },
  })

  const { data: syncProgress } = useQuery({
    queryKey: ['sync-job', activeJobId],
    queryFn: () => api.getSyncJob(activeJobId!),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || status === 'in_progress' || status === 'pending') return 2000
      return false
    },
  })

  useEffect(() => {
    if (!syncProgress) return
    if (syncProgress.status === 'completed') {
      setLastSyncResult(syncProgress)
      queryClient.invalidateQueries({ queryKey: ['messages', id] })
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      setActiveJobId(null)
      return
    }
    if (syncProgress.status === 'failed' || syncProgress.status === 'cancelled') {
      setLastSyncResult(syncProgress)
      setActiveJobId(null)
    }
  }, [syncProgress, id, queryClient])

  const isSyncRunning =
    syncMutation.isPending ||
    syncProgress?.status === 'in_progress' ||
    syncProgress?.status === 'pending'

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
          <div className="flex gap-2">
            <button
              onClick={() => syncMutation.mutate(500)}
              disabled={isSyncRunning}
              className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {isSyncRunning ? 'Syncing...' : 'Sync Latest (500)'}
            </button>
            {!isSyncRunning && (
              <button
                onClick={() => syncMutation.mutate(undefined)}
                title="Sync complete message history"
                className="px-3 py-2 bg-gray-600 text-white rounded-lg text-sm hover:bg-gray-700 transition"
              >
                Sync All
              </button>
            )}
          </div>
        </div>

        {syncMutation.isError && (
          <div className="mb-4 p-3 bg-red-100 text-red-700 rounded-lg">
            Sync failed: {(syncMutation.error as Error).message}
          </div>
        )}

        {lastSyncResult?.status === 'failed' && (
          <div className="mb-4 p-3 bg-red-100 text-red-700 rounded-lg">
            Sync failed: {lastSyncResult.error_message || 'Unknown sync failure'}
          </div>
        )}

        {lastSyncResult?.status === 'completed' && (
          <div className="mb-4 p-3 bg-green-100 text-green-700 rounded-lg">
            Synced {lastSyncResult.messages_processed} messages
          </div>
        )}

        {syncProgress?.status === 'pending' && syncProgress.retry_after_seconds && (
          <div className="mb-4 p-3 bg-yellow-100 text-yellow-800 rounded-lg">
            Sync rate-limited. Next retry in about {syncProgress.retry_after_seconds} seconds.
          </div>
        )}

        {isMessagesError && (
          <div className="mb-4 p-3 bg-red-100 text-red-700 rounded-lg flex items-center justify-between gap-4">
            <span>Failed to load messages: {(messagesError as Error).message}</span>
            <button
              onClick={() => refetchMessages()}
              className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 transition"
            >
              Retry
            </button>
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
