'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { use } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ChatAvatar } from '@/components/ChatAvatar'
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
    // Always rehydrate from newest page when entering a chat.
    queryClient.resetQueries({ queryKey: ['messages', id], exact: true })
  }, [id, queryClient])

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data: chatData } = useQuery({
    queryKey: ['chats'],
    queryFn: () => api.getChats(undefined, 500),
    enabled: !!user,
  })

  const chat = chatData?.chats.find((c) => c.id === id)

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
      queryClient.resetQueries({ queryKey: ['messages', id], exact: true })
      queryClient.invalidateQueries({ queryKey: ['messages', id], exact: true })
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

  const handleSyncMore = () => {
    if (!isSyncRunning) {
      syncMutation.mutate(500)
    }
  }

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-chat-bg">
      {/* Header */}
      <header className="flex items-center gap-3 px-3 py-2 bg-surface border-b shrink-0">
        <Link
          href="/chats"
          className="flex items-center justify-center w-8 h-8 text-tg-blue hover:opacity-70 transition-opacity"
          aria-label="Back to chats"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </Link>

        <ChatAvatar title={chat?.title || 'Chat'} size={40} />

        <div className="flex-1 min-w-0">
          <div className="font-medium text-[15px] text-primary truncate">
            {chat?.title || 'Chat'}
          </div>
          {chat && (
            <div className="text-[12px] text-tertiary">
              {chat.total_messages_synced.toLocaleString()} messages
            </div>
          )}
        </div>

        <ThemeToggle />
      </header>

      {/* Sync progress bar */}
      {isSyncRunning && syncProgress?.status === 'in_progress' && (
        <div className="px-4 py-2 bg-surface border-b shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <div className="animate-spin rounded-full h-3 w-3 border-2 border-tg-blue border-t-transparent" />
            <span className="text-[12px] text-secondary">
              Syncing...
              {syncProgress.messages_processed > 0 && ` ${syncProgress.messages_processed.toLocaleString()} messages`}
            </span>
          </div>
          {syncProgress.progress_percent != null && (
            <div className="w-full bg-surface-hover rounded-full h-1">
              <div
                className="bg-tg-blue h-1 rounded-full transition-all duration-500"
                style={{ width: `${syncProgress.progress_percent}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Status banners */}
      {syncMutation.isError && (
        <div className="px-4 py-2 bg-surface border-b text-[13px] text-primary shrink-0">
          Sync failed: {(syncMutation.error as Error).message}
        </div>
      )}
      {lastSyncResult?.status === 'failed' && (
        <div className="px-4 py-2 bg-surface border-b text-[13px] text-primary shrink-0">
          Sync failed: {lastSyncResult.error_message || 'Unknown error'}
        </div>
      )}
      {lastSyncResult?.status === 'completed' && (
        <div className="px-4 py-2 bg-surface border-b text-[13px] text-primary shrink-0">
          Synced {lastSyncResult.messages_processed.toLocaleString()} messages
        </div>
      )}

      {/* Message area */}
      <div className="flex-1 min-h-0">
        <MessageList chatId={id} onSyncMore={handleSyncMore} isSyncing={isSyncRunning} />
      </div>
    </div>
  )
}
