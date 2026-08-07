'use client'

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, resolveApiUrl, type Message } from '@/lib/api'

const ACTIVE_STATUSES = new Set(['pending', 'fetching', 'extracting', 'indexing', 'processing', 'retry_wait'])

function formatBytes(value: number | null | undefined) {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`
}

function safeLink(value: string) {
  const normalized = /^https?:\/\//i.test(value) || /^tg:\/\//i.test(value)
    ? value
    : `https://${value}`
  try {
    const url = new URL(normalized)
    return ['http:', 'https:', 'tg:'].includes(url.protocol) ? normalized : null
  } catch {
    return null
  }
}

export function MessageMediaDetails({ chatId, message }: { chatId: string; message: Message }) {
  const queryClient = useQueryClient()
  const contentKey = ['message-content', chatId, message.telegram_message_id]
  const content = useQuery({
    queryKey: contentKey,
    queryFn: () => api.getMessageContent(chatId, message.telegram_message_id),
    refetchInterval: (query) => {
      const status = query.state.data?.media_cache_status || query.state.data?.media_processing_status
      return status && ACTIVE_STATUSES.has(status) ? 2000 : false
    },
  })
  const prepare = useMutation({
    mutationFn: () => api.prepareMessageMedia(chatId, message.telegram_message_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: contentKey }),
  })
  const transcript = useInfiniteQuery({
    queryKey: ['message-transcript', chatId, message.telegram_message_id],
    queryFn: ({ pageParam }) => api.getTranscriptSegments(chatId, message.telegram_message_id, pageParam),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: !!content.data?.transcribed_at,
  })

  if (content.isLoading) {
    return <div className="mt-2 text-xs text-tertiary">Loading media status…</div>
  }
  if (content.error) {
    return <div className="mt-2 text-xs text-red-600">{(content.error as Error).message}</div>
  }

  const data = content.data
  const status = data?.media_cache_status || data?.media_processing_status || 'not prepared'
  const cachedBytes = data?.media_cached_bytes || 0
  const size = data?.media_file_size || 0
  const progress = size > 0 ? Math.min(100, Math.round((cachedBytes / size) * 100)) : null
  const mediaUrl = data?.media_download_url ? resolveApiUrl(data.media_download_url) : null
  const mime = data?.media_mime_type || ''
  const segments = transcript.data?.pages.flatMap((page) => page.segments) || []
  const links = Array.from(new Set([...(message.visible_urls || []), ...(message.hidden_urls || [])]))

  return (
    <div className="mt-2 space-y-2 border-t border-black/10 pt-2 text-xs min-w-[260px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{message.media_file_name || message.media_type || 'Media'}</span>
        <span className="text-tertiary">{status}</span>
        {progress !== null && status !== 'ready' && status !== 'ready_download_only' && (
          <span className="text-tertiary">{progress}% · {formatBytes(cachedBytes)} / {formatBytes(size)}</span>
        )}
      </div>

      {!['ready', 'ready_download_only'].includes(status) && !ACTIVE_STATUSES.has(status) && (
        <button
          type="button"
          onClick={() => prepare.mutate()}
          disabled={prepare.isPending}
          className="rounded border px-2 py-1 font-medium disabled:opacity-50"
        >
          {prepare.isPending ? 'Starting…' : 'Prepare media'}
        </button>
      )}
      {ACTIVE_STATUSES.has(status) && <div className="text-tertiary">Processing continues in the background.</div>}
      {data?.media_processing_error && <div className="text-red-600">{data.media_processing_error}</div>}

      {mediaUrl && mime.startsWith('audio/') && <audio controls preload="metadata" src={mediaUrl} className="w-full" />}
      {mediaUrl && mime.startsWith('video/') && <video controls preload="metadata" src={mediaUrl} className="w-full max-h-80" />}
      {mediaUrl && (
        <a href={mediaUrl} download className="inline-block font-medium underline underline-offset-2">
          Download original{data?.media_file_size ? ` · ${formatBytes(data.media_file_size)}` : ''}
        </a>
      )}
      {data?.telegram_message_url && (
        <a href={data.telegram_message_url} target="_blank" rel="noreferrer" className="ml-3 inline-block underline underline-offset-2">
          Open in Telegram
        </a>
      )}

      {data?.content_summary && <p className="whitespace-pre-wrap text-secondary">{data.content_summary}</p>}
      {segments.length > 0 && (
        <div className="max-h-64 space-y-1 overflow-y-auto rounded bg-black/5 p-2">
          {segments.map((segment) => (
            <div key={segment.sequence}>
              <span className="text-tertiary">{(segment.start_ms / 1000).toFixed(1)}s{segment.speaker ? ` · speaker ${segment.speaker}` : ''}</span>{' '}
              <span>{segment.text}</span>
            </div>
          ))}
          {transcript.hasNextPage && (
            <button type="button" onClick={() => transcript.fetchNextPage()} disabled={transcript.isFetchingNextPage} className="underline">
              {transcript.isFetchingNextPage ? 'Loading…' : 'Load more transcript'}
            </button>
          )}
        </div>
      )}
      {links.length > 0 && (
        <div className="space-y-1">
          {links.map((link) => {
            const href = safeLink(link)
            return href ? <a key={link} href={href} target="_blank" rel="noreferrer" className="block break-all underline">{link}</a> : null
          })}
        </div>
      )}
      {data?.media_sha256 && <div className="break-all font-mono text-[10px] text-tertiary">SHA-256 {data.media_sha256}</div>}
    </div>
  )
}
