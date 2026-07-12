'use client'

import type { DocumentSummary, DocumentLegalStatus } from '@/types/documents'

const STATUS_CONFIG: Record<DocumentLegalStatus, { label: string; cls: string }> = {
  ACTIVE: { label: 'Còn hiệu lực', cls: 'bg-green-500/10 text-green-600 dark:text-green-400' },
  NOT_YET_EFFECTIVE: { label: 'Chưa hiệu lực', cls: 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400' },
  PARTIALLY_EFFECTIVE: { label: 'Một phần', cls: 'bg-blue-500/10 text-blue-600 dark:text-blue-400' },
  REPLACED: { label: 'Đã thay thế', cls: 'bg-foreground/10 text-foreground/50' },
  REPEALED: { label: 'Đã hủy bỏ', cls: 'bg-red-500/10 text-red-500' },
  EXPIRED: { label: 'Hết hiệu lực', cls: 'bg-foreground/10 text-foreground/40' },
}

const DOC_TYPE_LABELS: Record<string, string> = {
  Law: 'Luật', Ordinance: 'Pháp lệnh', Decree: 'Nghị định',
  Decision: 'Quyết định', Circular: 'Thông tư',
  JointCircular: 'Thông tư liên tịch', Resolution: 'Nghị quyết',
}

interface DocumentListProps {
  items: DocumentSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  isLoading: boolean
  total: number
}

function SkeletonCard() {
  return (
    <div className="p-3 border-b border-border animate-pulse">
      <div className="h-3 bg-foreground/10 rounded w-3/4 mb-2" />
      <div className="h-2 bg-foreground/10 rounded w-1/2 mb-1" />
      <div className="h-2 bg-foreground/10 rounded w-1/3" />
    </div>
  )
}

export function DocumentList({ items, selectedId, onSelect, isLoading, total }: DocumentListProps) {
  if (isLoading) {
    return (
      <div className="flex-1 overflow-y-auto">
        {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-xs text-foreground/40">
        Không tìm thấy văn bản nào
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {items.map((doc) => {
        const status = STATUS_CONFIG[doc.status]
        const isSelected = doc.id === selectedId
        return (
          <button
            key={doc.id}
            onClick={() => onSelect(doc.id)}
            className={`w-full text-left p-3 border-b border-border transition-colors ${
              isSelected
                ? 'bg-brand/10 border-l-2 border-l-brand'
                : 'hover:bg-foreground/5'
            }`}
          >
            {/* Số hiệu */}
            <p className="text-xs font-semibold text-brand truncate">{doc.number}</p>

            {/* Tiêu đề */}
            {doc.title && (
              <p className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{doc.title}</p>
            )}

            {/* Meta */}
            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              {doc.doc_type && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/8 text-foreground/60">
                  {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
                </span>
              )}
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${status.cls}`}>
                {status.label}
              </span>
            </div>

            {/* Ngày hiệu lực */}
            {doc.effective_from && (
              <p className="text-[10px] text-foreground/40 mt-1">
                Hiệu lực: {new Date(doc.effective_from).toLocaleDateString('vi-VN')}
              </p>
            )}
          </button>
        )
      })}

      {/* Total count */}
      <div className="p-2 text-center text-[10px] text-foreground/40">
        {items.length}/{total} văn bản
      </div>
    </div>
  )
}
