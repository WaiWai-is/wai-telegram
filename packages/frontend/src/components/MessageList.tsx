'use client'

import { useRef, useEffect, useCallback, useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useTheme } from 'next-themes'
import { api, type Message } from '@/lib/api'
import { shouldShowDateSeparator, isSameGroup, formatDateSeparator } from '@/lib/chat-utils'
import { MessageBubble } from './MessageBubble'
import { DateSeparator } from './DateSeparator'

type ProcessedItem =
  | { type: 'sync-button' }
  | { type: 'date'; date: string; key: string }
  | { type: 'message'; message: Message; isFirstInGroup: boolean; isLastInGroup: boolean }

interface MessageListProps {
  chatId: string
  onSyncMore: () => void
  isSyncing: boolean
}

const PAGE_SIZE = 50

export function MessageList({ chatId, onSyncMore, isSyncing }: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const [initialScrollDone, setInitialScrollDone] = useState(false)
  const prevItemCountRef = useRef(0)
  const prevScrollHeightRef = useRef(0)

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    isError,
    error,
  } = useInfiniteQuery({
    queryKey: ['messages', chatId],
    queryFn: async ({ pageParam = null }) => {
      return api.getChatMessages(chatId, PAGE_SIZE, (pageParam as string | null) || undefined)
    },
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more) return undefined
      return lastPage.next_cursor ?? undefined
    },
    initialPageParam: null as string | null,
    refetchOnMount: 'always',
  })

  // Flatten all pages into a single array in chronological order (oldest first)
  const allMessages = useMemo(() => {
    if (!data?.pages) return []
    // Pages come newest-first from API. Flatten and reverse to get chronological.
    const flat = data.pages.flatMap((p) => p.messages)
    // Messages within each page are newest-first, so reverse entire array
    return [...flat].reverse()
  }, [data])

  // Build processed items: sync button + date separators interleaved with messages
  const items: ProcessedItem[] = useMemo(() => {
    const result: ProcessedItem[] = []

    // Show sync button at top when we've exhausted all API pages
    if (!hasNextPage && allMessages.length > 0) {
      result.push({ type: 'sync-button' })
    }

    for (let i = 0; i < allMessages.length; i++) {
      const msg = allMessages[i]
      const prevMsg = i > 0 ? allMessages[i - 1] : null

      // Date separator
      const hasDateSep = shouldShowDateSeparator(msg.sent_at, prevMsg?.sent_at ?? null)
      if (hasDateSep) {
        result.push({ type: 'date', date: msg.sent_at, key: `date-${msg.sent_at.slice(0, 10)}-${i}` })
      }

      // Message grouping — break group after date separators
      const sameGroupAsPrev = !hasDateSep && isSameGroup(msg, prevMsg)
      const nextMsg = i < allMessages.length - 1 ? allMessages[i + 1] : null
      const nextHasDateSep = nextMsg ? shouldShowDateSeparator(nextMsg.sent_at, msg.sent_at) : false
      const sameGroupAsNext = !nextHasDateSep && nextMsg ? isSameGroup(nextMsg, msg) : false

      result.push({
        type: 'message',
        message: msg,
        isFirstInGroup: !sameGroupAsPrev,
        isLastInGroup: !sameGroupAsNext,
      })
    }

    return result
  }, [allMessages, hasNextPage])

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const item = items[index]
      if (item.type === 'sync-button') return 56
      if (item.type === 'date') return 36
      return 52
    },
    overscan: 15,
  })

  // Initial scroll to bottom
  useEffect(() => {
    if (items.length > 0 && !initialScrollDone && !isLoading) {
      // Small delay to let virtualizer measure
      requestAnimationFrame(() => {
        virtualizer.scrollToIndex(items.length - 1, { align: 'end' })
        setInitialScrollDone(true)
      })
    }
  }, [items.length, initialScrollDone, isLoading, virtualizer])

  // Reset initial scroll when chat changes
  useEffect(() => {
    setInitialScrollDone(false)
    prevItemCountRef.current = 0
  }, [chatId])

  // Preserve scroll position when older messages are prepended
  useEffect(() => {
    const el = parentRef.current
    if (!el || !initialScrollDone) return

    const prevCount = prevItemCountRef.current
    const newCount = items.length

    if (prevCount > 0 && newCount > prevCount) {
      // The virtualizer has new items at the top; restore scroll offset
      const prevHeight = prevScrollHeightRef.current
      requestAnimationFrame(() => {
        const newHeight = virtualizer.getTotalSize()
        const delta = newHeight - prevHeight
        if (delta > 0) {
          el.scrollTop += delta
        }
      })
    }

    prevItemCountRef.current = newCount
    prevScrollHeightRef.current = virtualizer.getTotalSize()
  }, [items.length, initialScrollDone, virtualizer])

  // Auto-fetch more if viewport isn't filled
  useEffect(() => {
    if (!initialScrollDone || !hasNextPage || isFetchingNextPage) return
    const el = parentRef.current
    if (el && el.scrollHeight <= el.clientHeight) {
      prevScrollHeightRef.current = virtualizer.getTotalSize()
      fetchNextPage()
    }
  }, [initialScrollDone, hasNextPage, isFetchingNextPage, items.length, fetchNextPage, virtualizer])

  // Load older messages when scrolling near top
  const handleScroll = useCallback(() => {
    const el = parentRef.current
    if (!el) return

    if (el.scrollTop < 300 && hasNextPage && !isFetchingNextPage) {
      prevScrollHeightRef.current = virtualizer.getTotalSize()
      fetchNextPage()
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, virtualizer])

  // Floating date pill — find topmost visible message's date
  const virtualItems = virtualizer.getVirtualItems()
  let floatingDate: string | null = null
  for (const vi of virtualItems) {
    const item = items[vi.index]
    if (item.type === 'message') {
      floatingDate = formatDateSeparator(item.message.sent_at)
      break
    }
    if (item.type === 'date') {
      floatingDate = formatDateSeparator(item.date)
      break
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full text-primary">
        Failed to load messages: {(error as Error).message}
      </div>
    )
  }

  if (allMessages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-tertiary">
        No messages synced yet
      </div>
    )
  }

  return (
    <div className="relative h-full">
      {/* Floating date pill */}
      {floatingDate && initialScrollDone && (
        <div className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none">
          <span className="px-3 py-[3px] rounded-full bg-date-pill-bg text-date-pill-text text-[13px] select-none">
            {floatingDate}
          </span>
        </div>
      )}

      {/* Loading indicator for older messages */}
      {isFetchingNextPage && (
        <div className="absolute top-2 left-0 right-0 z-20 flex justify-center pointer-events-none">
          <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary border-t-transparent" />
        </div>
      )}

      <div
        ref={parentRef}
        className="h-full overflow-auto px-3 sm:px-4"
        onScroll={handleScroll}
        style={{ opacity: initialScrollDone ? 1 : 0 }}
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
            // Push messages to bottom when they don't fill the container
            marginTop: Math.max(0, (parentRef.current?.clientHeight ?? 0) - virtualizer.getTotalSize()),
          }}
        >
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const item = items[virtualItem.index]

            return (
              <div
                key={virtualItem.index}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                {item.type === 'sync-button' && (
                  <div className="flex justify-center py-3">
                    <button
                      onClick={onSyncMore}
                      disabled={isSyncing}
                      className="px-4 py-2 rounded-full bg-tg-blue text-white text-[13px] font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
                    >
                      {isSyncing ? 'Syncing...' : 'Sync More Messages'}
                    </button>
                  </div>
                )}

                {item.type === 'date' && <DateSeparator date={item.date} />}

                {item.type === 'message' && (
                  <MessageBubble
                    message={item.message}
                    isFirstInGroup={item.isFirstInGroup}
                    isLastInGroup={item.isLastInGroup}
                    isDark={isDark}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
