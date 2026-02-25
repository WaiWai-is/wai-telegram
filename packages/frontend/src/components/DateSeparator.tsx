import { formatDateSeparator } from '@/lib/chat-utils'

interface DateSeparatorProps {
  date: string
}

export function DateSeparator({ date }: DateSeparatorProps) {
  return (
    <div className="flex justify-center py-2">
      <span className="px-3 py-[3px] rounded-full bg-date-pill-bg text-date-pill-text text-[13px] select-none">
        {formatDateSeparator(date)}
      </span>
    </div>
  )
}
