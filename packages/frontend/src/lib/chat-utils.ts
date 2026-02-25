import { format, isToday, isYesterday, isSameDay, differenceInMinutes, differenceInDays, isThisYear, parseISO } from 'date-fns'

// 12 Telegram-style hues evenly spaced
const SENDER_HUES = [0, 30, 60, 120, 160, 200, 220, 240, 270, 300, 330, 350]

function hashCode(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

export function getSenderColor(senderId: number | string, isDark: boolean): string {
  const idx = hashCode(String(senderId)) % SENDER_HUES.length
  const h = SENDER_HUES[idx]
  return isDark ? `hsl(${h}, 80%, 65%)` : `hsl(${h}, 70%, 45%)`
}

export function getInitialsColor(title: string): string {
  const idx = hashCode(title) % SENDER_HUES.length
  const h = SENDER_HUES[idx]
  return `hsl(${h}, 55%, 50%)`
}

export function getInitials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].substring(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

export function formatMessageTime(dateStr: string): string {
  return format(parseISO(dateStr), 'HH:mm')
}

export function formatDateSeparator(dateStr: string): string {
  const date = parseISO(dateStr)
  if (isToday(date)) return 'Today'
  if (isYesterday(date)) return 'Yesterday'
  return format(date, 'MMMM d')
}

export function shouldShowDateSeparator(currentDateStr: string, previousDateStr: string | null): boolean {
  if (!previousDateStr) return true
  return !isSameDay(parseISO(currentDateStr), parseISO(previousDateStr))
}

export function formatChatListTime(dateStr: string): string {
  const date = parseISO(dateStr)
  const now = new Date()
  if (isToday(date)) return format(date, 'h:mm a')
  if (isYesterday(date)) return 'Yesterday'
  if (differenceInDays(now, date) < 7) return format(date, 'EEE')
  if (isThisYear(date)) return format(date, 'MMM d')
  return format(date, 'MMM yyyy')
}

export function isSameGroup(
  current: { sender_id: number | null; sent_at: string; is_outgoing: boolean },
  previous: { sender_id: number | null; sent_at: string; is_outgoing: boolean } | null
): boolean {
  if (!previous) return false
  if (current.is_outgoing !== previous.is_outgoing) return false
  if (current.sender_id !== previous.sender_id) return false
  return Math.abs(differenceInMinutes(parseISO(current.sent_at), parseISO(previous.sent_at))) <= 3
}
