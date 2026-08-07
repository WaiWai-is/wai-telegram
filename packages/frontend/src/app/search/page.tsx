'use client'

import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { format } from 'date-fns'
import { api, resolveApiUrl } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/ThemeToggle'
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

  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['search', searchQuery],
    queryFn: ({ pageParam }) => api.search(searchQuery, undefined, 20, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: !!user && !!searchQuery,
  })
  const results = data?.pages.flatMap((page) => page.results) ?? []

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setSearchQuery(query)
  }

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/" className="text-sm text-tertiary hover:text-primary transition-colors mb-2 block">
              &larr; Back to Dashboard
            </Link>
            <h1 className="text-3xl font-light tracking-tight text-primary">
              Search Messages
            </h1>
          </div>
          <ThemeToggle />
        </div>

        <form onSubmit={handleSearch} className="mb-8">
          <div className="flex gap-4">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by meaning, not just keywords..."
              className="flex-1 px-4 py-3 border rounded-lg bg-transparent text-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              type="submit"
              disabled={!query.trim()}
              className="px-6 py-3 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
            >
              Search
            </button>
          </div>
          <p className="mt-2 text-sm text-tertiary">
            AI-powered semantic search finds messages by meaning
          </p>
        </form>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
          </div>
        ) : error ? (
          <div className="p-4 border rounded-lg text-primary">
            Search failed. Please try again.
          </div>
        ) : results.length ? (
          <div className="space-y-4">
            <p className="text-sm text-tertiary">
              Loaded {results.length} results
            </p>
            {results.map((result) => (
              <div
                key={result.id}
                className="p-4 border rounded-lg"
              >
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <span className="font-medium text-primary">
                      {result.chat_title}
                    </span>
                    <span className="text-tertiary mx-2">&middot;</span>
                    <span className="text-sm text-tertiary">
                      {result.sender_name || (result.is_outgoing ? 'You' : 'Unknown')}
                    </span>
                  </div>
                  <div className="text-sm text-tertiary">
                    {format(new Date(result.sent_at), 'MMM d, yyyy')}
                  </div>
                </div>
                <p className="text-secondary whitespace-pre-wrap">
                  {result.text || result.content_summary || result.content_preview || `[${result.media_type || 'media'}]`}
                </p>
                {result.media_file_name && (
                  <p className="mt-2 text-sm font-medium text-secondary">{result.media_file_name}</p>
                )}
                {(result.visible_urls?.length || result.hidden_urls?.length) ? (
                  <div className="mt-2 space-y-1 text-xs">
                    {Array.from(new Set([...(result.visible_urls || []), ...(result.hidden_urls || [])])).map((url) => {
                      const href = /^https?:\/\//i.test(url) || /^tg:\/\//i.test(url) ? url : `https://${url}`
                      return <a key={url} href={href} target="_blank" rel="noreferrer" className="block break-all underline">{url}</a>
                    })}
                  </div>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-3 text-xs">
                  {result.telegram_message_url && <a href={result.telegram_message_url} target="_blank" rel="noreferrer" className="underline">Open in Telegram</a>}
                  {result.media_download_url && resolveApiUrl(result.media_download_url) && (
                    <a href={resolveApiUrl(result.media_download_url) ?? undefined} download className="underline">Download media</a>
                  )}
                  {result.deleted_at && <span className="text-red-600">Deleted in Telegram · kept in archive</span>}
                </div>
                <div className="mt-2 text-xs text-tertiary">
                  Relevance: {(result.similarity * 100).toFixed(0)}%
                </div>
              </div>
            ))}
            {hasNextPage && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="w-full px-4 py-3 border rounded-lg text-primary hover:bg-secondary/10 disabled:opacity-50"
              >
                {isFetchingNextPage ? 'Loading more…' : 'Load more results'}
              </button>
            )}
          </div>
        ) : searchQuery ? (
          <div className="text-center py-8 text-tertiary">
            No messages found for &quot;{searchQuery}&quot;
          </div>
        ) : null}
      </div>
    </main>
  )
}
