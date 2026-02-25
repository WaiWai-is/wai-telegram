import { getInitials, getInitialsColor } from '@/lib/chat-utils'

interface ChatAvatarProps {
  title: string
  size?: number
}

export function ChatAvatar({ title, size = 48 }: ChatAvatarProps) {
  const bg = getInitialsColor(title)
  const initials = getInitials(title)
  const fontSize = size * 0.38

  return (
    <div
      className="rounded-full flex items-center justify-center text-white font-medium shrink-0"
      style={{ width: size, height: size, backgroundColor: bg, fontSize }}
    >
      {initials}
    </div>
  )
}
