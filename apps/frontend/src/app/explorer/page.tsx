'use client'

import { useSearchParams, useRouter } from 'next/navigation'
import { FilterBar } from '@/components/explorer/FilterBar'
import { DocumentList } from '@/components/explorer/DocumentList'
import { DocumentDetailPanel } from '@/components/explorer/DocumentDetail'
import { useDocuments } from '@/hooks/useDocuments'
import { useDocumentDetail } from '@/hooks/useDocumentDetail'
import { Separator } from '@/components/ui/separator'
import { FileText, Search } from 'lucide-react'

export default function ExplorerPage() {
   const searchParams = useSearchParams()
   const router = useRouter()

   // 1.   Đọc query params để auto-select
   const paramDocId = searchParams.get('document')
   const paramArticleId = searchParams.get('article') ?? undefined
   const paramClauseId = searchParams.get('clause') ?? undefined

   const selectedDocId = paramDocId

   const { items, pagination, filters, isLoading, error, applyFilters, setPage } = useDocuments()
   const { detail, isLoading: detailLoading, error: detailError } = useDocumentDetail(selectedDocId)

   // 2.   URL là source of truth cho document đang chọn.
   const handleSelect = (docId: string) => {
      router.replace(`/explorer?document=${docId}`)
   }

   // 3.   Khi click quan hệ văn bản, navigate sang document đó
   const handleNavigateDoc = (docId: string) => {
      router.replace(`/explorer?document=${docId}`)
   }

   return (
      <div className="flex h-screen overflow-hidden bg-background">
         {/* Left panel — filter + list */}
         <div className="flex flex-col w-72 shrink-0 border-r border-border bg-card">
            {/* Panel header */}
            <div className="px-4 py-3 border-b border-border shrink-0">
               <div className="flex items-center gap-2">
                  <Search className="w-4 h-4 text-muted-foreground" />
                  <h1 className="text-sm font-semibold">Tra cứu văn bản</h1>
               </div>
            </div>

            {/* Filters */}
            <FilterBar filters={filters} onFilterChange={applyFilters} />

            {/* Document list */}
            <DocumentList
               items={items}
               selectedId={selectedDocId}
               onSelect={handleSelect}
               isLoading={isLoading}
               total={pagination.total}
               error={error}
            />

            {/* Pagination footer */}
            {pagination.total > pagination.page_size && (
               <div className="p-2 border-t border-border shrink-0 flex justify-between items-center">
                  <button
                     className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-30"
                     disabled={pagination.page <= 1}
                     onClick={() => setPage(pagination.page - 1)}
                  >
                     ← Trước
                  </button>
                  <span className="text-[11px] text-muted-foreground">Trang {pagination.page}</span>
                  <button
                     className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-30"
                     disabled={pagination.page * pagination.page_size >= pagination.total}
                     onClick={() => setPage(pagination.page + 1)}
                  >
                     Tiếp →
                  </button>
               </div>
            )}
         </div>

         <Separator orientation="vertical" />

         {/* Right panel — document detail */}
         <div className="flex-1 overflow-hidden bg-background">
            {!selectedDocId && (
               <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                  <FileText className="w-12 h-12 opacity-20" />
                  <p className="text-sm">Chọn một văn bản để xem nội dung</p>
               </div>
            )}

            {selectedDocId && detailLoading && (
               <div className="flex items-center justify-center h-full">
                  <div className="text-sm text-muted-foreground">Đang tải văn bản...</div>
               </div>
            )}

            {selectedDocId && detailError && !detailLoading && (
               <div className="flex items-center justify-center h-full px-6 text-sm text-destructive text-center">
                  Không thể tải nội dung văn bản: {detailError}
               </div>
            )}

            {detail && !detailLoading && !detailError && (
               <DocumentDetailPanel
                  doc={detail}
                  highlightArticleId={paramArticleId}
                  highlightClauseId={paramClauseId}
                  onNavigateDoc={handleNavigateDoc}
               />
            )}
         </div>
      </div>
   )
}
