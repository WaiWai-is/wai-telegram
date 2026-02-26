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
  const isTranscribed = !!message.transcribed_at
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
          {isTranscribed && (
            <span className="inline-flex items-center mr-1 align-middle" title="Transcribed from voice">
              <svg className="w-3.5 h-3.5 text-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" x2="12" y1="19" y2="22" />
              </svg>
            </span>
          )}
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
