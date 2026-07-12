'use client'

import { useEffect, useState } from 'react'
import { documentsApi } from '@/lib/api/documents'
import type { GraphData } from '@/types/documents'

/**
 * Chỉ fetch graph khi enabled=true (lazy load).
 * DocumentDetail.tsx set enabled=true chỉ khi user click tab "Đồ thị".
 */
export function useDocumentGraph(docId: string | null, enabled: boolean) {
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Chỉ fetch khi có docId VÀ enabled=true
    if (!docId || !enabled) return

    let cancelled = false
    setIsLoading(true)
    setError(null)

    documentsApi
      .getGraph(docId)
      .then((res) => {
        if (!cancelled) setGraph(res)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : 'Không thể tải đồ thị')
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [docId, enabled])

  return { graph, isLoading, error }
}
