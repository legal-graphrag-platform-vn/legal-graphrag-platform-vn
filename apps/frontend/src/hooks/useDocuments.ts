'use client'

import { useCallback, useEffect, useState } from 'react'
import { documentsApi } from '@/lib/api/documents'
import type {
  DocumentListResponse,
  DocumentSummary,
  FilterState,
  PageMeta,
} from '@/types/documents'

export function useDocuments() {
  const [items, setItems] = useState<DocumentSummary[]>([])
  const [pagination, setPagination] = useState<PageMeta>({
    page: 1,
    page_size: 20,
    total: 0,
  })
  const [filters, setFilters] = useState<FilterState>({})
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res: DocumentListResponse = await documentsApi.list(
        page,
        20,
        filters,
      )
      setItems(res.items)
      setPagination(res.pagination)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải danh sách văn bản')
    } finally {
      setIsLoading(false)
    }
  }, [page, filters])

  useEffect(() => {
    fetch()
  }, [fetch])

  const applyFilters = useCallback((newFilters: FilterState) => {
    setFilters(newFilters)
    setPage(1) // Reset về trang 1 khi filter thay đổi
  }, [])

  return { items, pagination, filters, isLoading, error, setPage, applyFilters }
}
