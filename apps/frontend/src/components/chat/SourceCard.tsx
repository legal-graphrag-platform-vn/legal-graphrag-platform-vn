import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Source } from '../../types/chat'
import { BookOpen, ExternalLink, Calendar } from 'lucide-react'
import { SourceDetailModal } from './SourceDetailModal'
import { sourceHref } from '@/lib/source-link'

interface SourceCardProps {
   sources: Source[]
}

const LABEL_COLORS: Record<string, string> = {
   Article: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20',
   Clause: 'bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-500/20',
   Point: 'bg-violet-500/10 text-violet-700 dark:text-violet-400 border-violet-500/20',
}

const LABEL_VN: Record<string, string> = {
   Article: 'Điều',
   Clause: 'Khoản',
   Point: 'Điểm',
}

export function SourceCard({ sources }: SourceCardProps) {
   const [activeSource, setActiveSource] = useState<Source | null>(null)
   const router = useRouter()

   if (!sources || sources.length === 0) return null

   const handleClick = (source: Source) => {
      const href = sourceHref(source)
      if (href) {
         router.push(href)
      } else {
         // Fallback: mở modal chi tiết
         setActiveSource(source)
      }
   }

   return (
      <div className="mt-4 border-t border-border pt-4">
         <div className="flex items-center gap-2 mb-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            <BookOpen size={13} className="text-primary" />
            <span>Nguồn tham chiếu ({sources.length})</span>
         </div>

         <div className="flex flex-wrap gap-2">
            {sources.map((source, index) => (
               <button
                  key={source.id || index}
                  onClick={() => handleClick(source)}
                  title={sourceHref(source) ? 'Mở trong Tra cứu văn bản' : 'Xem chi tiết'}
                  className="group flex flex-col gap-1 px-3 py-2 text-xs rounded-lg bg-card hover:bg-muted border border-border transition-colors duration-200 text-left max-w-[220px]"
               >
                  {/* Row 1: index + label badge + link icon */}
                  <div className="flex items-center gap-1.5">
                     <span className="flex items-center justify-center w-4.5 h-4.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold shrink-0">
                        {index + 1}
                     </span>
                     {source.label && (
                        <span
                           className={`text-[10px] px-1 py-0.5 rounded border ${LABEL_COLORS[source.label] ?? ''}`}
                        >
                           {LABEL_VN[source.label] ?? source.label}
                        </span>
                     )}
                     {source.document_id && (
                        <ExternalLink
                           size={10}
                           className="ml-auto text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        />
                     )}
                  </div>

                  {/* Row 2: citation label */}
                  <span className="font-medium text-foreground truncate leading-snug">
                     {source.citation_label ?? source.title}
                  </span>

                  {/* Row 3: effective date nếu có */}
                  {source.effective_from && (
                     <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                        <Calendar size={9} />
                        <span>
                           {new Date(source.effective_from).toLocaleDateString('vi-VN')}
                           {source.effective_to &&
                              ` – ${new Date(source.effective_to).toLocaleDateString('vi-VN')}`}
                        </span>
                     </div>
                  )}

                  {/* Row 4: score nếu có */}
                  {source.final_score !== undefined && (
                     <div className="flex items-center gap-1">
                        <div
                           className="h-1 rounded-full bg-primary"
                           style={{
                              width: `${Math.round(source.final_score * 100)}%`,
                              maxWidth: '60px',
                           }}
                        />
                        <span className="text-[10px] text-muted-foreground">
                           {(source.final_score * 100).toFixed(0)}%
                        </span>
                     </div>
                  )}
               </button>
            ))}
         </div>

         {activeSource && (
            <SourceDetailModal source={activeSource} onClose={() => setActiveSource(null)} />
         )}
      </div>
   )
}
