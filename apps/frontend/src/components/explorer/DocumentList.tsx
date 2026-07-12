'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { DocumentSummary, DocumentLegalStatus } from '@/types/documents'

const STATUS_CONFIG: Record<DocumentLegalStatus, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  ACTIVE:              { label: 'Còn hiệu lực',     variant: 'default' },
  NOT_YET_EFFECTIVE:   { label: 'Chưa hiệu lực',    variant: 'secondary' },
  PARTIALLY_EFFECTIVE: { label: 'Một phần',          variant: 'secondary' },
  REPLACED:            { label: 'Đã thay thế',       variant: 'outline' },
  REPEALED:            { label: 'Đã hủy bỏ',         variant: 'destructive' },
  EXPIRED:             { label: 'Hết hiệu lực',      variant: 'outline' },
}

const DOC_TYPE_LABELS: Record<string, string> = {
  Law: 'Luật', Ordinance: 'Pháp lệnh', Decree: 'Nghị định',
  Decision: 'Quyết định', Circular: 'Thông tư',
  JointCircular: 'Thông tư LT', Resolution: 'Nghị quyết',
}

interface DocumentListProps {
  items: DocumentSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  isLoading: boolean
  total: number
}

export function DocumentList({ items, selectedId, onSelect, isLoading, total }: DocumentListProps) {
  if (isLoading) {
    return (
      <ScrollArea className="flex-1">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="p-3 border-b border-border space-y-2">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-2 w-1/2" />
            <Skeleton className="h-2 w-1/3" />
          </div>
        ))}
      </ScrollArea>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-xs text-muted-foreground">
        Không tìm thấy văn bản nào
      </div>
    )
  }

  return (
    <ScrollArea className="flex-1">
      {items.map((doc) => {
        const status = STATUS_CONFIG[doc.status]
        const isSelected = doc.id === selectedId
        return (
          <button
            key={doc.id}
            onClick={() => onSelect(doc.id)}
            className={`w-full text-left p-3 border-b border-border transition-colors ${
              isSelected
                ? 'bg-primary/5 border-l-2 border-l-primary'
                : 'hover:bg-muted/50'
            }`}
          >
            <p className="text-xs font-semibold text-primary truncate">{doc.number}</p>

            {doc.title && (
              <p className="text-xs text-foreground/80 mt-0.5 line-clamp-2 leading-snug">
                {doc.title}
              </p>
            )}

            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              {doc.doc_type && (
                <Badge variant="outline" className="text-[10px] px-1.5 h-4 rounded-sm font-normal">
                  {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
                </Badge>
              )}
              <Badge variant={status.variant} className="text-[10px] px-1.5 h-4 rounded-sm font-normal">
                {status.label}
              </Badge>
            </div>

            {doc.effective_from && (
              <p className="text-[10px] text-muted-foreground mt-1">
                Hiệu lực: {new Date(doc.effective_from).toLocaleDateString('vi-VN')}
              </p>
            )}
          </button>
        )
      })}

      <div className="p-2 text-center text-[10px] text-muted-foreground">
        {items.length} / {total} văn bản
      </div>
    </ScrollArea>
  )
}
