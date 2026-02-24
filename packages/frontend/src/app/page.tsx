'use client'

import { useAuth } from '@/lib/auth'
import Link from 'next/link'

export default function Home() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (!user) {
    return (
      <main className="flex flex-col items-center justify-center min-h-screen p-8">
        <h1 className="text-4xl font-light tracking-tight mb-4 text-primary">
          Telegram AI Message Manager
        </h1>
        <p className="text-lg text-secondary mb-8 text-center max-w-xl">
          Search your Telegram messages with AI-powered semantic search.
          Get daily digests and integrate with Claude via MCP.
        </p>
        <div className="flex gap-4">
          <Link
            href="/login"
            className="px-6 py-3 bg-primary text-surface rounded-lg hover:opacity-80 transition-opacity"
          >
            Sign In
          </Link>
          <Link
            href="/register"
            className="px-6 py-3 border rounded-lg text-primary hover:bg-surface-hover transition-colors"
          >
            Create Account
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <nav className="flex justify-between items-center mb-8 pb-4 border-b">
        <h1 className="text-xl font-light tracking-tight text-primary">
          Telegram AI
        </h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-secondary">
            {user.email}
          </span>
          <button
            onClick={() => useAuth.getState().logout()}
            className="text-sm text-tertiary hover:text-primary transition-colors"
          >
            Sign Out
          </button>
        </div>
      </nav>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Link
          href="/chats"
          className="p-6 border rounded-xl hover:bg-surface-hover transition-colors"
        >
          <h2 className="text-lg font-medium mb-2 text-primary">
            Chats
          </h2>
          <p className="text-secondary">
            Browse and sync your Telegram conversations
          </p>
        </Link>

        <Link
          href="/search"
          className="p-6 border rounded-xl hover:bg-surface-hover transition-colors"
        >
          <h2 className="text-lg font-medium mb-2 text-primary">
            Search
          </h2>
          <p className="text-secondary">
            Find messages with AI-powered semantic search
          </p>
        </Link>

        <Link
          href="/digests"
          className="p-6 border rounded-xl hover:bg-surface-hover transition-colors"
        >
          <h2 className="text-lg font-medium mb-2 text-primary">
            Digests
          </h2>
          <p className="text-secondary">
            View AI-generated daily summaries
          </p>
        </Link>

        <Link
          href="/settings"
          className="p-6 border rounded-xl hover:bg-surface-hover transition-colors"
        >
          <h2 className="text-lg font-medium mb-2 text-primary">
            Settings
          </h2>
          <p className="text-secondary">
            Connect Telegram and manage API keys
          </p>
        </Link>
      </div>
    </main>
  )
}
