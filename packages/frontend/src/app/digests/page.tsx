'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { format } from 'date-fns'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

export default function DigestsPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useAuth()
  const queryClient = useQueryClient()
  const [selectedDigest, setSelectedDigest] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login')
    }
  }, [user, authLoading, router])

  const { data: digests, isLoading } = useQuery({
    queryKey: ['digests'],
    queryFn: () => api.getDigests(),
    enabled: !!user,
  })

  const generateMutation = useMutation({
    mutationFn: () => api.generateDigest(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['digests'] })
    },
  })

  if (authLoading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  const selected = digests?.find((d) => d.id === selectedDigest) || digests?.[0]

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/" className="text-sm text-blue-600 hover:underline mb-2 block">
              ← Back to Dashboard
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Daily Digests
            </h1>
          </div>
          <button
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
          >
            {generateMutation.isPending ? 'Generating...' : 'Generate Yesterday\'s Digest'}
          </button>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        ) : !digests?.length ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            <p className="mb-4">No digests generated yet.</p>
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="text-blue-600 hover:underline"
            >
              Generate your first daily digest
            </button>
          </div>
        ) : (
          <div className="grid md:grid-cols-3 gap-6">
            <div className="space-y-2">
              {digests.map((digest) => (
                <button
                  key={digest.id}
                  onClick={() => setSelectedDigest(digest.id)}
                  className={`w-full text-left p-3 rounded-lg transition ${
                    selected?.id === digest.id
                      ? 'bg-blue-600 text-white'
                      : 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-900 dark:text-white'
                  }`}
                >
                  <div className="font-medium">
                    {format(new Date(digest.digest_date), 'EEEE, MMMM d')}
                  </div>
                  <div className={`text-sm ${
                    selected?.id === digest.id ? 'text-blue-200' : 'text-gray-500 dark:text-gray-400'
                  }`}>
                    {(digest.summary_stats as { total_messages?: number })?.total_messages || 0} messages
                  </div>
                </button>
              ))}
            </div>

            <div className="md:col-span-2">
              {selected && (
                <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm">
                  <h2 className="text-xl font-bold mb-4 text-gray-900 dark:text-white">
                    {format(new Date(selected.digest_date), 'EEEE, MMMM d, yyyy')}
                  </h2>
                  <div className="prose dark:prose-invert max-w-none">
                    <div className="whitespace-pre-wrap text-gray-700 dark:text-gray-300">
                      {selected.content}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
