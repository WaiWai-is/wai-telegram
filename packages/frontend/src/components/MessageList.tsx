'use client'

import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { format } from 'date-fns'
import clsx from 'clsx'

interface Message {
  id: string
  text: string | null
  sender_name: string | null
  is_outgoing: boolean
  sent_at: string
  has_media: boolean
  media_type: string | null
}

interface MessageListProps {
  messages: Message[]
  isLoading?: boolean
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 10,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  if (!messages.length) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        No messages found
      </div>
    )
  }

  return (
    <div ref={parentRef} className="h-[600px] overflow-auto">
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => {
          const message = messages[virtualItem.index]
          return (
            <div
              key={message.id}
              data-index={virtualItem.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualItem.start}px)`,
              }}
              className="py-2"
            >
              <div
                className={clsx(
                  'max-w-[80%] rounded-lg p-3',
                  message.is_outgoing
                    ? 'ml-auto bg-blue-600 text-white'
                    : 'mr-auto bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
                )}
              >
                {!message.is_outgoing && message.sender_name && (
                  <div className="text-xs font-semibold mb-1 text-blue-600 dark:text-blue-400">
                    {message.sender_name}
                  </div>
                )}
                <div className="whitespace-pre-wrap break-words">
                  {message.text || (message.has_media ? `[${message.media_type || 'media'}]` : '')}
                </div>
                <div
                  className={clsx(
                    'text-xs mt-1',
                    message.is_outgoing ? 'text-blue-200' : 'text-gray-500 dark:text-gray-400'
                  )}
                >
                  {format(new Date(message.sent_at), 'MMM d, h:mm a')}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
