'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { format } from 'date-fns'
import { api, Chat } from '@/lib/api'
import { useAuth } from '@/lib/auth'
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
      // Step 1: Discover chats from Telegram
      await api.refreshChats()
      queryClient.invalidateQueries({ queryKey: ['chats'] })

      // Step 2: Start bulk message sync (500 per chat)
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
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  const getChatTypeIcon = (type: Chat['chat_type']) => {
    switch (type) {
      case 'private':
        return '\u{1F464}'
      case 'group':
        return '\u{1F465}'
      case 'supergroup':
        return '\u{1F465}'
      case 'channel':
        return '\u{1F4E2}'
      default:
        return '\u{1F4AC}'
    }
  }

  const isBusy = isRefreshing || isBulkActive

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/" className="text-sm text-tertiary hover:text-primary transition-colors mb-2 block">
              &larr; Back to Dashboard
            </Link>
            <h1 className="text-3xl font-light tracking-tight text-primary">
              Your Chats
            </h1>
          </div>
          <button
            onClick={handleRefresh}
            disabled={isBusy}
            className="px-4 py-2 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
          >
            {isRefreshing ? 'Refreshing...' : isBulkActive ? 'Syncing...' : 'Refresh from Telegram'}
          </button>
        </div>

        {refreshError && (
          <div className="mb-4 p-3 border rounded-lg">
            <span className="text-sm text-primary">
              {refreshError}
            </span>
          </div>
        )}

        {/* Bulk sync progress banner */}
        {isBulkActive && (
          <div className="mb-4 p-3 border rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-primary border-t-transparent" />
              <span className="text-sm font-medium text-primary">
                Syncing messages...
              </span>
              {bulkProgress?.total_chats != null && (
                <span className="text-sm text-secondary">
                  {bulkProgress.chats_completed}/{bulkProgress.total_chats} chats
                  &middot; {bulkProgress.messages_processed.toLocaleString()} messages
                </span>
              )}
            </div>
            {bulkProgress?.total_chats != null && bulkProgress.total_chats > 0 && (
              <div className="w-full bg-surface-hover rounded-full h-1.5">
                <div
                  className="bg-primary h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${bulkProgress.progress_percent ?? 0}%` }}
                />
              </div>
            )}
            {bulkProgress?.current_chat && (
              <p className="text-xs text-tertiary mt-1 truncate">
                Currently: {bulkProgress.current_chat}
              </p>
            )}
          </div>
        )}

        {/* Bulk sync completed */}
        {bulkProgress?.status === 'completed' && (
          <div className="mb-4 p-3 border rounded-lg">
            <span className="text-sm text-primary">
              Sync complete &mdash; {bulkProgress.messages_processed.toLocaleString()} messages synced
            </span>
          </div>
        )}

        {/* Bulk sync failed */}
        {bulkProgress?.status === 'failed' && (
          <div className="mb-4 p-3 border rounded-lg">
            <span className="text-sm text-primary">
              Sync failed: {bulkProgress.error_message || 'Unknown error'}
            </span>
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
          </div>
        ) : error ? (
          <div className="p-4 border rounded-lg text-primary">
            Failed to load chats. Make sure you&apos;ve connected your Telegram account.
          </div>
        ) : !data?.chats.length ? (
          <div className="text-center py-12 text-tertiary">
            <p className="mb-4">No chats synced yet.</p>
            <Link
              href="/settings"
              className="text-tertiary hover:text-primary transition-colors"
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
                className="block p-4 border rounded-lg hover:bg-surface-hover transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{getChatTypeIcon(chat.chat_type)}</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-primary truncate">
                      {chat.title}
                    </h3>
                    <div className="flex gap-4 text-sm text-tertiary items-center">
                      {syncStatusByChat.has(chat.id) ? (
                        <span className="flex items-center gap-1 text-secondary">
                          <div className="animate-spin rounded-full h-3 w-3 border border-secondary border-t-transparent" />
                          Syncing...
                        </span>
                      ) : chat.total_messages_synced > 0 ? (
                        <span>{chat.total_messages_synced.toLocaleString()} messages</span>
                      ) : (
                        <span className="text-tertiary">Not synced</span>
                      )}
                      {chat.last_sync_at && (
                        <span>
                          Synced {format(new Date(chat.last_sync_at), 'MMM d, h:mm a')}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-tertiary">&rarr;</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
