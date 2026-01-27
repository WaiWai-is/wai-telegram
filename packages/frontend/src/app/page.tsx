'use client'

import { useAuth } from '@/lib/auth'
import Link from 'next/link'

export default function Home() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  if (!user) {
    return (
      <main className="flex flex-col items-center justify-center min-h-screen p-8">
        <h1 className="text-4xl font-bold mb-4 text-gray-900 dark:text-white">
          Telegram AI Message Manager
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 mb-8 text-center max-w-xl">
          Search your Telegram messages with AI-powered semantic search.
          Get daily digests and integrate with Claude via MCP.
        </p>
        <div className="flex gap-4">
          <Link
            href="/login"
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
          >
            Sign In
          </Link>
          <Link
            href="/register"
            className="px-6 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
          >
            Create Account
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <nav className="flex justify-between items-center mb-8 pb-4 border-b border-gray-200 dark:border-gray-700">
        <h1 className="text-xl font-bold text-gray-900 dark:text-white">
          Telegram AI
        </h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600 dark:text-gray-400">
            {user.email}
          </span>
          <button
            onClick={() => useAuth.getState().logout()}
            className="text-sm text-red-600 hover:text-red-700"
          >
            Sign Out
          </button>
        </div>
      </nav>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Link
          href="/chats"
          className="p-6 bg-white dark:bg-gray-800 rounded-xl shadow-sm hover:shadow-md transition"
        >
          <h2 className="text-lg font-semibold mb-2 text-gray-900 dark:text-white">
            Chats
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Browse and sync your Telegram conversations
          </p>
        </Link>

        <Link
          href="/search"
          className="p-6 bg-white dark:bg-gray-800 rounded-xl shadow-sm hover:shadow-md transition"
        >
          <h2 className="text-lg font-semibold mb-2 text-gray-900 dark:text-white">
            Search
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Find messages with AI-powered semantic search
          </p>
        </Link>

        <Link
          href="/digests"
          className="p-6 bg-white dark:bg-gray-800 rounded-xl shadow-sm hover:shadow-md transition"
        >
          <h2 className="text-lg font-semibold mb-2 text-gray-900 dark:text-white">
            Digests
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            View AI-generated daily summaries
          </p>
        </Link>

        <Link
          href="/settings"
          className="p-6 bg-white dark:bg-gray-800 rounded-xl shadow-sm hover:shadow-md transition"
        >
          <h2 className="text-lg font-semibold mb-2 text-gray-900 dark:text-white">
            Settings
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Connect Telegram and manage API keys
          </p>
        </Link>
      </div>
    </main>
  )
}
