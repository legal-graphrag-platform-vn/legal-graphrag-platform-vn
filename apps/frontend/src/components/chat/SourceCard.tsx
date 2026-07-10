import React, { useState } from 'react'
import { Source } from '../../types/chat'
import { BookOpen } from 'lucide-react'
import { SourceDetailModal } from './SourceDetailModal'

interface SourceCardProps {
   sources: Source[]
}

export function SourceCard({ sources }: SourceCardProps) {
   const [activeSource, setActiveSource] = useState<Source | null>(null)

   if (!sources || sources.length === 0) return null

   return (
      <div className="mt-4 border-t border-border pt-4">
         <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-zinc-500 uppercase tracking-wider dark:text-zinc-400">
            <BookOpen size={14} className="text-emerald-500" />
            <span>Nguồn tham chiếu ({sources.length})</span>
         </div>
         <div className="flex flex-wrap gap-2">
            {sources.map((source, index) => (
               <button
                  key={source.id || index}
                  onClick={() => setActiveSource(source)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-card hover:bg-zinc-150/40 text-foreground border border-border transition-colors duration-200 dark:bg-zinc-800/40 dark:hover:bg-zinc-800 dark:text-zinc-250 cursor-pointer text-left max-w-[200px] truncate"
               >
                  <span className="flex items-center justify-center w-4.5 h-4.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-bold dark:bg-emerald-950/60 dark:text-emerald-300">
                     {index + 1}
                  </span>
                  <span className="truncate">{source.title}</span>
                  {source.page && (
                     <span className="text-[10px] text-zinc-400 dark:text-zinc-500">
                        tr. {source.page}
                     </span>
                  )}
               </button>
            ))}
         </div>

         {/* Source Detail Modal (Tách thành component riêng để dễ quản lý) */}
         {activeSource && (
            <SourceDetailModal source={activeSource} onClose={() => setActiveSource(null)} />
         )}
      </div>
   )
}
