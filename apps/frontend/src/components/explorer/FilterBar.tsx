'use client'

import type { FilterState, DocumentLegalStatus } from '@/types/documents'

const DOC_TYPES = ['Law', 'Ordinance', 'Decree', 'Decision', 'Circular', 'JointCircular', 'Resolution']
const STATUSES: { value: DocumentLegalStatus; label: string }[] = [
  { value: 'ACTIVE', label: 'Còn hiệu lực' },
  { value: 'NOT_YET_EFFECTIVE', label: 'Chưa có hiệu lực' },
  { value: 'PARTIALLY_EFFECTIVE', label: 'Một phần hiệu lực' },
  { value: 'REPLACED', label: 'Đã thay thế' },
  { value: 'REPEALED', label: 'Đã hủy bỏ' },
  { value: 'EXPIRED', label: 'Hết hiệu lực' },
]

interface FilterBarProps {
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
}

export function FilterBar({ filters, onFilterChange }: FilterBarProps) {
  const update = (partial: Partial<FilterState>) =>
    onFilterChange({ ...filters, ...partial })

  return (
    <div className="flex flex-col gap-2 p-3 border-b border-border">
      {/* Loại văn bản */}
      <select
        className="w-full text-xs bg-card border border-border rounded px-2 py-1.5 text-foreground focus:outline-none focus:border-brand"
        value={filters.doc_type ?? ''}
        onChange={(e) => update({ doc_type: e.target.value || undefined })}
      >
        <option value="">Tất cả loại văn bản</option>
        {DOC_TYPES.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      {/* Trạng thái */}
      <select
        className="w-full text-xs bg-card border border-border rounded px-2 py-1.5 text-foreground focus:outline-none focus:border-brand"
        value={filters.status ?? ''}
        onChange={(e) =>
          update({ status: (e.target.value as DocumentLegalStatus) || undefined })
        }
      >
        <option value="">Tất cả trạng thái</option>
        {STATUSES.map((s) => (
          <option key={s.value} value={s.value}>{s.label}</option>
        ))}
      </select>

      {/* Cơ quan ban hành */}
      <input
        type="text"
        placeholder="Cơ quan ban hành..."
        className="w-full text-xs bg-card border border-border rounded px-2 py-1.5 text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-brand"
        value={filters.issuer ?? ''}
        onChange={(e) => update({ issuer: e.target.value || undefined })}
      />

      {/* Năm */}
      <input
        type="number"
        placeholder="Năm ban hành..."
        className="w-full text-xs bg-card border border-border rounded px-2 py-1.5 text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-brand"
        value={filters.year ?? ''}
        min={1945}
        max={new Date().getFullYear()}
        onChange={(e) =>
          update({ year: e.target.value ? Number(e.target.value) : undefined })
        }
      />

      {/* Reset */}
      {Object.values(filters).some(Boolean) && (
        <button
          onClick={() => onFilterChange({})}
          className="text-xs text-brand hover:text-brand-hover text-left"
        >
          Xóa bộ lọc
        </button>
      )}
    </div>
  )
}
