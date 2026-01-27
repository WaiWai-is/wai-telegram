'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { format } from 'date-fns'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function SearchPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const [query, setQuery] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', searchQuery],
    queryFn: () => api.search(searchQuery),
    enabled: !!user && !!searchQuery,
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setSearchQuery(query)
  }

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <Link href="/" className="text-sm text-blue-600 hover:underline mb-2 block">
          ← Back to Dashboard
        </Link>
        <h1 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
          Search Messages
        </h1>

        <form onSubmit={handleSearch} className="mb-8">
          <div className="flex gap-4">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by meaning, not just keywords..."
              className="flex-1 px-4 py-3 border rounded-lg bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white"
            />
            <button
              type="submit"
              disabled={!query.trim()}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
            >
              Search
            </button>
          </div>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            AI-powered semantic search finds messages by meaning
          </p>
        </form>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        ) : error ? (
          <div className="p-4 bg-red-100 text-red-700 rounded-lg">
            Search failed. Please try again.
          </div>
        ) : data?.results.length ? (
          <div className="space-y-4">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Found {data.total} results
            </p>
            {data.results.map((result) => (
              <div
                key={result.id}
                className="p-4 bg-white dark:bg-gray-800 rounded-lg"
              >
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {result.chat_title}
                    </span>
                    <span className="text-gray-500 dark:text-gray-400 mx-2">·</span>
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {result.sender_name || (result.is_outgoing ? 'You' : 'Unknown')}
                    </span>
                  </div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">
                    {format(new Date(result.sent_at), 'MMM d, yyyy')}
                  </div>
                </div>
                <p className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                  {result.text}
                </p>
                <div className="mt-2 text-xs text-gray-400">
                  Relevance: {(result.similarity * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </div>
        ) : searchQuery ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            No messages found for &quot;{searchQuery}&quot;
          </div>
        ) : null}
      </div>
    </main>
  )
}
