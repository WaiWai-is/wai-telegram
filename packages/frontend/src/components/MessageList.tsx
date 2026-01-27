'use client'

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
    <div className="space-y-4">
      {messages.map((message) => (
        <div
          key={message.id}
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
      ))}
    </div>
  )
}
