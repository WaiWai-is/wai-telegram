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
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  const selected = digests?.find((d) => d.id === selectedDigest) || digests?.[0]

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <Link href="/" className="text-sm text-tertiary hover:text-primary transition-colors mb-2 block">
              &larr; Back to Dashboard
            </Link>
            <h1 className="text-3xl font-light tracking-tight text-primary">
              Daily Digests
            </h1>
          </div>
          <button
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
            className="px-4 py-2 bg-primary text-surface rounded-lg hover:opacity-80 disabled:opacity-50 transition-opacity"
          >
            {generateMutation.isPending ? 'Generating...' : 'Generate Yesterday\'s Digest'}
          </button>
        </div>

        {generateMutation.isError && (
          <div className="mb-4 p-3 border rounded-lg text-primary">
            Failed to generate digest: {(generateMutation.error as Error).message}
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
          </div>
        ) : !digests?.length ? (
          <div className="text-center py-12 text-tertiary">
            <p className="mb-4">No digests generated yet.</p>
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="text-tertiary hover:text-primary transition-colors"
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
                  className={`w-full text-left p-3 rounded-lg transition-colors ${
                    selected?.id === digest.id
                      ? 'bg-primary text-surface'
                      : 'border hover:bg-surface-hover text-primary'
                  }`}
                >
                  <div className="font-medium">
                    {format(new Date(digest.digest_date), 'EEEE, MMMM d')}
                  </div>
                  <div className={`text-sm ${
                    selected?.id === digest.id ? 'opacity-60' : 'text-tertiary'
                  }`}>
                    {(digest.summary_stats as { total_messages?: number })?.total_messages || 0} messages
                  </div>
                </button>
              ))}
            </div>

            <div className="md:col-span-2">
              {selected && (
                <div className="border rounded-xl p-6">
                  <h2 className="text-xl font-light tracking-tight mb-4 text-primary">
                    {format(new Date(selected.digest_date), 'EEEE, MMMM d, yyyy')}
                  </h2>
                  <div className="prose dark:prose-invert max-w-none">
                    <div className="whitespace-pre-wrap text-secondary">
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
