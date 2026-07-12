'use client'

import { useEffect, useState } from 'react'
import { documentsApi } from '@/lib/api/documents'
import type { DocumentDetail } from '@/types/documents'

export function useDocumentDetail(docId: string | null) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!docId) {
      setDetail(null)
      return
    }

    let cancelled = false
    setIsLoading(true)
    setError(null)

    documentsApi
      .getDetail(docId)
      .then((res) => {
        if (!cancelled) setDetail(res)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : 'Không thể tải văn bản')
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [docId])

  return { detail, isLoading, error }
}
