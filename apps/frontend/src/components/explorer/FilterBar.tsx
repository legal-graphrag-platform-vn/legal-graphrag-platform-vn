'use client'

import {
   Select,
   SelectContent,
   SelectItem,
   SelectTrigger,
   SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-react'
import type { FilterState, DocumentLegalStatus } from '@/types/documents'

const DOC_TYPES = [
   { value: 'Law', label: 'Luật' },
   { value: 'Ordinance', label: 'Pháp lệnh' },
   { value: 'Decree', label: 'Nghị định' },
   { value: 'Decision', label: 'Quyết định' },
   { value: 'Circular', label: 'Thông tư' },
   { value: 'JointCircular', label: 'Thông tư liên tịch' },
   { value: 'Resolution', label: 'Nghị quyết' },
]

const DOC_TYPE_LABELS = Object.fromEntries(DOC_TYPES.map(({ value, label }) => [value, label]))

const STATUSES: { value: DocumentLegalStatus; label: string }[] = [
   { value: 'ACTIVE', label: 'Còn hiệu lực' },
   { value: 'NOT_YET_EFFECTIVE', label: 'Chưa có hiệu lực' },
   { value: 'PARTIALLY_EFFECTIVE', label: 'Một phần hiệu lực' },
   { value: 'REPLACED', label: 'Đã thay thế' },
   { value: 'REPEALED', label: 'Đã hủy bỏ' },
   { value: 'EXPIRED', label: 'Hết hiệu lực' },
]

const STATUS_LABELS = Object.fromEntries(STATUSES.map(({ value, label }) => [value, label]))

interface FilterBarProps {
   filters: FilterState
   onFilterChange: (filters: FilterState) => void
}

export function FilterBar({ filters, onFilterChange }: FilterBarProps) {
   const update = (partial: Partial<FilterState>) => onFilterChange({ ...filters, ...partial })

   const hasFilters = Object.values(filters).some(Boolean)

   return (
      <div className="flex flex-col gap-2 p-3 border-b border-border bg-muted/30">
         <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider px-0.5">
            Bộ lọc
         </p>

         <Select
            items={DOC_TYPE_LABELS}
            value={filters.doc_type ?? null}
            onValueChange={(v) => update({ doc_type: v === '_all' ? undefined : (v ?? undefined) })}
         >
            <SelectTrigger className="h-8 text-xs">
               <SelectValue placeholder="Tất cả loại văn bản" />
            </SelectTrigger>
            <SelectContent>
               <SelectItem value="_all">Tất cả loại văn bản</SelectItem>
               {DOC_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                     {t.label}
                  </SelectItem>
               ))}
            </SelectContent>
         </Select>

         <Select
            items={STATUS_LABELS}
            value={(filters.status ?? null) as string | null}
            onValueChange={(v) =>
               update({ status: (v === '_all' ? undefined : v) as DocumentLegalStatus | undefined })
            }
         >
            <SelectTrigger className="h-8 text-xs">
               <SelectValue placeholder="Tất cả trạng thái" />
            </SelectTrigger>
            <SelectContent>
               <SelectItem value="_all">Tất cả trạng thái</SelectItem>
               {STATUSES.map((s) => (
                  <SelectItem key={s.value} value={s.value} className="text-xs">
                     {s.label}
                  </SelectItem>
               ))}
            </SelectContent>
         </Select>

         <Input
            className="h-8 text-xs"
            placeholder="Cơ quan ban hành..."
            value={filters.issuer ?? ''}
            onChange={(e) => update({ issuer: e.target.value || undefined })}
         />

         <Input
            type="number"
            className="h-8 text-xs"
            placeholder="Năm ban hành..."
            value={filters.year ?? ''}
            min={1945}
            max={new Date().getFullYear()}
            onChange={(e) => update({ year: e.target.value ? Number(e.target.value) : undefined })}
         />

         {hasFilters && (
            <Button
               variant="ghost"
               size="sm"
               className="h-7 text-xs text-muted-foreground justify-start px-1"
               onClick={() => onFilterChange({})}
            >
               <X className="w-3 h-3 mr-1" />
               Xóa bộ lọc
            </Button>
         )}
      </div>
   )
}
