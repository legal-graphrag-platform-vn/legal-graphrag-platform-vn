import type { ReasoningPath } from '@/types/chat'

interface ExplanationPanelProps {
   temporalNotes: string[]
   reasoningPaths: ReasoningPath[]
}

export function ExplanationPanel({ temporalNotes, reasoningPaths }: ExplanationPanelProps) {
   if (temporalNotes.length === 0 && reasoningPaths.length === 0) return null

   return (
      <details className="rounded-standard border border-border bg-card px-3.5 py-2.5 text-[13px]">
         <summary className="cursor-pointer font-semibold text-foreground">
            Giải thích căn cứ
         </summary>
         <div className="mt-3 space-y-3 text-muted-foreground">
            {temporalNotes.length > 0 && (
               <div>
                  <div className="font-medium text-foreground">Hiệu lực theo thời gian</div>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                     {temporalNotes.map((note) => (
                        <li key={note}>{note}</li>
                     ))}
                  </ul>
               </div>
            )}
            {reasoningPaths.length > 0 && (
               <div>
                  <div className="font-medium text-foreground">Đường dẫn pháp lý</div>
                  <ul className="mt-1 space-y-2">
                     {reasoningPaths.map((path) => (
                        <li key={path.path_id}>
                           <div>{path.description || path.path_id}</div>
                           {path.nodes.length > 0 && (
                              <div className="mt-0.5 font-mono text-[11px]">
                                 {path.nodes.join(' → ')}
                              </div>
                           )}
                        </li>
                     ))}
                  </ul>
               </div>
            )}
         </div>
      </details>
   )
}
