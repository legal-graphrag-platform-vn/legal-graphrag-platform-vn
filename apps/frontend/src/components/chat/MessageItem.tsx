import { Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Message } from '../../types/chat'
import { SourceCard } from './SourceCard'

interface MessageItemProps {
   message: Message
   isLast: boolean
   isStreaming: boolean
}

export function MessageItem({ message, isLast, isStreaming }: MessageItemProps) {
   const isUser = message.role === 'user'

   return (
      <div className="w-full flex justify-center py-4 px-4 md:px-0">
         <div className="w-full max-w-3xl">
            {isUser ? (
               /* User Message - Right-aligned with Avatar on the right */
               <div className="flex justify-end items-start gap-3.5">
                  <div className="bg-user-bubble text-user-bubble-text px-4 py-2.5 rounded-2xl max-w-[75%] text-[15px] leading-relaxed wrap-break-word shadow-2xs">
                     {message.content}
                  </div>

                  {/* User Initials Avatar */}
                  <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 flex items-center justify-center font-bold text-[11px] shrink-0 select-none border border-indigo-200/30">
                     A
                  </div>
               </div>
            ) : (
               /* Assistant Message - Left-aligned with Sparkles Avatar on the left */
               <div className="flex justify-start items-start gap-3.5 animate-in fade-in duration-300">
                  {/* AI Avatar */}
                  <div className="w-8 h-8 rounded-full bg-linear-to-tr from-emerald-600 to-teal-500 text-white flex items-center justify-center shadow-md shadow-emerald-500/10 shrink-0 select-none animate-pulse-slow">
                     <Sparkles size={14} />
                  </div>

                  <div className="flex-1 flex flex-col space-y-3 min-w-0">
                     {/* Markdown Content / Thinking Indicator */}
                     <div className="prose dark:prose-invert prose-zinc max-w-none text-zinc-900 dark:text-zinc-100 leading-relaxed text-[15px] space-y-4">
                        {isLast && isStreaming && !message.content ? (
                           /* Bouncing Dots (Messenger Style) */
                           <div className="flex items-center gap-1.5 py-2.5 px-0.5 select-none animate-in fade-in duration-200">
                              <div className="w-2 h-2 bg-zinc-500 dark:bg-zinc-400 rounded-full animate-bounce [animation-duration:1s] [animation-delay:0s]" />
                              <div className="w-2 h-2 bg-zinc-500 dark:bg-zinc-400 rounded-full animate-bounce [animation-duration:1s] [animation-delay:0.2s]" />
                              <div className="w-2 h-2 bg-zinc-500 dark:bg-zinc-400 rounded-full animate-bounce [animation-duration:1s] [animation-delay:0.4s]" />
                           </div>
                        ) : (
                           <>
                              <ReactMarkdown
                                 remarkPlugins={[remarkGfm]}
                                 components={{
                                    // Code block custom styling
                                    code({ node, className, children, ...props }) {
                                       const match = /language-(\w+)/.exec(className || '')
                                       const inline = !match
                                       return inline ? (
                                          <code className="bg-code-bg px-1.5 py-0.5 rounded-md text-foreground font-mono text-[13px] font-semibold border border-code-border">
                                             {children}
                                          </code>
                                       ) : (
                                          <div className="my-4 rounded-xl overflow-hidden border border-code-border shadow-xs">
                                             <div className="flex items-center justify-between px-4 py-2 bg-code-header border-b border-code-border text-[11px] font-mono text-zinc-500 dark:text-zinc-400 select-none">
                                                <span>{match[1]}</span>
                                             </div>
                                             <pre className="p-4 bg-zinc-950 text-zinc-100 overflow-x-auto font-mono text-xs leading-relaxed">
                                                <code className={className} {...props}>
                                                   {children}
                                                </code>
                                             </pre>
                                          </div>
                                       )
                                    },
                                    // Table styles
                                    table({ children }) {
                                       return (
                                          <div className="my-4 overflow-x-auto rounded-lg border border-border">
                                             <table className="min-w-full divide-y divide-border">
                                                {children}
                                             </table>
                                          </div>
                                       )
                                    },
                                    thead({ children }) {
                                       return (
                                          <thead className="bg-zinc-50 dark:bg-zinc-900/50">
                                             {children}
                                          </thead>
                                       )
                                    },
                                    th({ children }) {
                                       return (
                                          <th className="px-4 py-2.5 text-left text-xs font-semibold text-zinc-600 dark:text-zinc-300 uppercase tracking-wider">
                                             {children}
                                          </th>
                                       )
                                    },
                                    td({ children }) {
                                       return (
                                          <td className="px-4 py-2.5 whitespace-nowrap text-sm text-zinc-600 dark:text-zinc-400 border-t border-border">
                                             {children}
                                          </td>
                                       )
                                    },
                                 }}
                              >
                                 {message.content}
                              </ReactMarkdown>
                           </>
                        )}
                     </div>

                     {/* Citations / RAG sources */}
                     {message.sources && message.sources.length > 0 && (
                        <SourceCard sources={message.sources} />
                     )}
                  </div>
               </div>
            )}
         </div>
      </div>
   )
}
