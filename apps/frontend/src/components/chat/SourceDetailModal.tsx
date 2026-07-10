import React from 'react'
import { Source } from '../../types/chat'
import { BookOpen, X, ExternalLink } from 'lucide-react'

interface SourceDetailModalProps {
   source: Source
   onClose: () => void
}

export function SourceDetailModal({ source, onClose }: SourceDetailModalProps) {
   return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs transition-opacity duration-300">
         <div className="relative w-full max-w-2xl bg-card rounded-2xl shadow-2xl border border-border flex flex-col max-h-[85vh] animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between p-5 border-b border-border">
               <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400">
                     <BookOpen size={20} />
                  </div>
                  <div>
                     <h3 className="font-semibold text-lg text-foreground truncate max-w-[400px]">
                        {source.title}
                     </h3>
                     {source.page && (
                        <p className="text-xs text-zinc-500 dark:text-zinc-400">
                           Trang: {source.page}{' '}
                           {source.score ? `• Độ khớp: ${(source.score * 100).toFixed(0)}%` : ''}
                        </p>
                     )}
                  </div>
               </div>
               <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg hover:bg-zinc-150/50 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-650 dark:hover:text-zinc-200 transition-colors cursor-pointer"
                  title="Đóng"
               >
                  <X size={18} />
               </button>
            </div>

            {/* Content (Scrollable) */}
            <div className="p-6 overflow-y-auto text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap font-sans">
               {source.content}
            </div>

            {/* Footer */}
            {source.url && (
               <div className="flex justify-end p-4 border-t border-border bg-sidebar/55 rounded-b-2xl">
                  <a
                     href={source.url}
                     target="_blank"
                     rel="noopener noreferrer"
                     className="flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors shadow-xs"
                  >
                     <span>Xem tài liệu gốc</span>
                     <ExternalLink size={14} />
                  </a>
               </div>
            )}
         </div>
      </div>
   )
}
