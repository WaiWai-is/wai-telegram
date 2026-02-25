'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api, Chat } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ChatAvatar } from '@/components/ChatAvatar'
import { formatChatListTime } from '@/lib/chat-utils'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import type { SyncJob } from '@/lib/api'

export default function ChatsPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

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

  // Bulk sync job progress — polls every 2s when active
  const { data: bulkProgress } = useQuery({
    queryKey: ['sync-job', bulkJobId],
    queryFn: () => api.getSyncJob(bulkJobId!),
    enabled: !!bulkJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'in_progress' || status === 'pending') return 2000
      if (status === 'completed' || status === 'failed') {
        queryClient.invalidateQueries({ queryKey: ['chats'] })
        return false
      }
      return false
    },
  })

  const isBulkActive = bulkProgress?.status === 'in_progress' || bulkProgress?.status === 'pending'

  // Recent sync jobs for per-chat status indicators
  const { data: recentJobs } = useQuery({
    queryKey: ['sync-jobs'],
    queryFn: () => api.getSyncJobs(100),
    enabled: !!user,
    refetchInterval: isBulkActive ? 3000 : false,
  })

  // Map chat_id -> active sync job
  const syncStatusByChat = useMemo(() => new Map(
    recentJobs
      ?.filter((j): j is SyncJob & { chat_id: string } =>
        j.chat_id != null && (j.status === 'in_progress' || j.status === 'pending')
      )
      .map(j => [j.chat_id, j] as const) ?? []
  ), [recentJobs])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    setRefreshError(null)
    try {
      await api.refreshChats()
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      const job = await api.syncAll(500)
      setBulkJobId(job.id)
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : 'Failed to start sync')
    } finally {
      setIsRefreshing(false)
    }
  }

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  const isBusy = isRefreshing || isBulkActive

  return (
    <div className="h-screen flex flex-col bg-surface">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center justify-center w-8 h-8 text-tg-blue hover:opacity-70 transition-opacity"
            aria-label="Back to dashboard"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </Link>
          <h1 className="text-[17px] font-semibold text-primary">Chats</h1>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <button
            onClick={handleRefresh}
            disabled={isBusy}
            className="px-3 py-1.5 rounded-lg bg-tg-blue text-white text-[13px] font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {isRefreshing ? 'Refreshing...' : isBulkActive ? 'Syncing...' : 'Refresh'}
          </button>
        </div>
      </header>

      {/* Sync banners */}
      {refreshError && (
        <div className="px-4 py-2 border-b text-[13px] text-primary">
          {refreshError}
        </div>
      )}

      {isBulkActive && (
        <div className="px-4 py-2 border-b shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <div className="animate-spin rounded-full h-3 w-3 border-2 border-tg-blue border-t-transparent" />
            <span className="text-[12px] text-secondary">
              Syncing messages...
              {bulkProgress?.total_chats != null && (
                <> {bulkProgress.chats_completed}/{bulkProgress.total_chats} chats &middot; {bulkProgress.messages_processed.toLocaleString()} messages</>
              )}
            </span>
          </div>
          {bulkProgress?.total_chats != null && bulkProgress.total_chats > 0 && (
            <div className="w-full bg-surface-hover rounded-full h-1">
              <div
                className="bg-tg-blue h-1 rounded-full transition-all duration-500"
                style={{ width: `${bulkProgress.progress_percent ?? 0}%` }}
              />
            </div>
          )}
        </div>
      )}

      {bulkProgress?.status === 'completed' && (
        <div className="px-4 py-2 border-b text-[13px] text-primary">
          Sync complete &mdash; {bulkProgress.messages_processed.toLocaleString()} messages synced
        </div>
      )}

      {bulkProgress?.status === 'failed' && (
        <div className="px-4 py-2 border-b text-[13px] text-primary">
          Sync failed: {bulkProgress.error_message || 'Unknown error'}
        </div>
      )}

      {/* Chat list */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
          </div>
        ) : error ? (
          <div className="px-4 py-8 text-center text-primary text-[14px]">
            Failed to load chats. Make sure you&apos;ve connected your Telegram account.
          </div>
        ) : !data?.chats.length ? (
          <div className="text-center py-12 text-tertiary">
            <p className="mb-4 text-[14px]">No chats synced yet.</p>
            <Link
              href="/settings"
              className="text-tg-blue hover:opacity-70 transition-opacity text-[14px]"
            >
              Connect your Telegram account to get started
            </Link>
          </div>
        ) : (
          <div className="divide-y">
            {data.chats.map((chat) => {
              const isSyncing = syncStatusByChat.has(chat.id)
              const isGroup = chat.chat_type === 'group' || chat.chat_type === 'supergroup' || chat.chat_type === 'channel'
              const hasPreview = !!chat.last_message_text
              const hasUnread = chat.unread_count > 0

              return (
                <Link
                  key={chat.id}
                  href={`/chats/${chat.id}`}
                  className="flex items-center gap-3 px-4 py-[10px] hover:bg-chat-list-hover transition-colors"
                >
                  <ChatAvatar title={chat.title} size={48} />
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-baseline gap-2">
                      <span className="font-medium text-[15px] text-primary truncate">
                        {chat.title}
                      </span>
                      {chat.last_activity_at && (
                        <span className={`text-[12px] shrink-0 ${hasUnread ? 'text-tg-blue font-medium' : 'text-tertiary'}`}>
                          {formatChatListTime(chat.last_activity_at)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 min-w-0 text-[14px] text-tertiary truncate">
                        {isSyncing ? (
                          <span className="flex items-center gap-1 text-secondary">
                            <span className="inline-block animate-spin rounded-full h-3 w-3 border border-secondary border-t-transparent" />
                            Syncing...
                          </span>
                        ) : hasPreview ? (
                          <span>
                            {isGroup && chat.last_message_sender_name && (
                              <span className="text-primary font-medium">
                                {chat.last_message_sender_name}:{' '}
                              </span>
                            )}
                            {chat.last_message_text}
                          </span>
                        ) : chat.total_messages_synced > 0 ? (
                          <span>{chat.total_messages_synced.toLocaleString()} messages</span>
                        ) : (
                          <span>Not synced</span>
                        )}
                      </div>
                      {hasUnread && (
                        <span className="shrink-0 min-w-[20px] h-[20px] px-1.5 rounded-full bg-tg-blue text-white text-[11px] font-medium flex items-center justify-center">
                          {chat.unread_count > 999 ? '999+' : chat.unread_count}
                        </span>
                      )}
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
