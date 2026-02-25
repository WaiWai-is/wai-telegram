'use client'

import clsx from 'clsx'
import { formatMessageTime, getSenderColor } from '@/lib/chat-utils'
import type { Message } from '@/lib/api'

interface MessageBubbleProps {
  message: Message
  isFirstInGroup: boolean
  isLastInGroup: boolean
  isDark: boolean
}

export function MessageBubble({ message, isFirstInGroup, isLastInGroup, isDark }: MessageBubbleProps) {
  const isOut = message.is_outgoing
  const time = formatMessageTime(message.sent_at)
  const displayText = message.text || (message.has_media ? `[${message.media_type || 'media'}]` : '')

  return (
    <div
      className={clsx(
        'flex',
        isOut ? 'justify-end' : 'justify-start',
        isLastInGroup ? 'mb-[6px]' : 'mb-[2px]'
      )}
    >
      <div
        className={clsx(
          'max-w-[65%] px-[9px] py-[6px] relative',
          isOut ? 'bg-bubble-out text-bubble-out-text' : 'bg-bubble-in text-bubble-in-text',
          // Tail on last in group
          isLastInGroup && isOut && 'bubble-tail-out',
          isLastInGroup && !isOut && 'bubble-tail-in',
          // Corner rounding
          isOut
            ? clsx(
                'rounded-l-lg rounded-tr-lg',
                isLastInGroup ? 'rounded-br-[4px]' : 'rounded-br-lg'
              )
            : clsx(
                'rounded-r-lg rounded-tl-lg',
                isLastInGroup ? 'rounded-bl-[4px]' : 'rounded-bl-lg'
              )
        )}
      >
        {/* Sender name — first in group, incoming only */}
        {isFirstInGroup && !isOut && message.sender_name && (
          <div
            className="text-[13px] font-medium mb-[2px] leading-tight"
            style={{ color: getSenderColor(message.sender_id ?? message.sender_name, isDark) }}
          >
            {message.sender_name}
          </div>
        )}

        {/* Message text with inline timestamp */}
        <div className="whitespace-pre-wrap break-words text-[14.5px] leading-[1.35]">
          {displayText}
          {/* Invisible spacer to prevent timestamp from overlapping text */}
          <span className="inline-block w-[52px]" />
        </div>

        {/* Floating timestamp */}
        <span className="absolute bottom-[4px] right-[8px] text-[11.5px] text-timestamp leading-none select-none">
          {time}
        </span>
      </div>
    </div>
  )
}
