'use client'

import React, { startTransition, useState, useEffect, useRef } from 'react'
import { Sidebar } from '@/components/layout/Sidebar'
import { MessageItem } from '@/components/chat/MessageItem'
import { AuthModal } from '@/components/auth/AuthModal'
import { useChatStream } from '@/hooks/useChatStream'
import { apiGet, apiPatch, apiDelete } from '@/lib/api/client'
import { ChatSession } from '@/types/chat'
import {
   Plus,
   ArrowUp,
   Share2,
   MoreHorizontal,
   PanelLeft,
   Image as ImageIcon,
   PenLine,
   Globe,
} from 'lucide-react'

interface UserProfile {
   user_id: string
   username: string
   full_name?: string | null
}

interface ServerConversationSummary {
   id: string
   title?: string | null
   created_at?: string | null
}

interface ServerCitation {
   ordinal?: number
   unit_id: string
   citation_label: string
   document_id: string
   deep_link: string
}

interface ServerMessage {
   id: string
   role: string
   content: string
   citations?: ServerCitation[]
   explanation?: {
      temporal_notes?: string[]
      reasoning_paths?: Array<{
         path_id: string
         description: string
         nodes: string[]
      }>
   } | null
   metadata?: {
      intent?: string
      retrieval_mode?: string
      cannot_answer?: boolean
      insufficiency_message?: string
   } | null
   created_at?: string | null
}

interface ServerConversationDetail {
   title?: string | null
   messages?: ServerMessage[]
}

export default function ChatPage() {
   const [sessions, setSessions] = useState<ChatSession[]>([])
   const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
   const [inputText, setInputText] = useState('')
   const [sidebarOpen, setSidebarOpen] = useState(true)
   // Auth state (login required to chat). null = not logged in; undefined = checking.
   const [user, setUser] = useState<UserProfile | null | undefined>(undefined)
   const [showAuth, setShowAuth] = useState(false)

   // Custom hook for SSE Streaming
   const { messages, setMessages, isStreaming, sendMessage, clearMessages } = useChatStream([])

   const messagesEndRef = useRef<HTMLDivElement>(null)
   const textareaRef = useRef<HTMLTextAreaElement>(null)

   // Rebuild the sidebar from the server for the CURRENT principal, dropping any
   // locally cached sessions that belong to a different (previous) principal.
   const reloadConversationsForPrincipal = async () => {
      clearMessages()
      try {
         const items = await apiGet<ServerConversationSummary[]>('/api/v1/conversations')
         const list = Array.isArray(items) ? items : []
         const serverSessions: ChatSession[] = list.map((item) => ({
            id: item.id,
            title: item.title || 'Cuộc hội thoại mới',
            messages: [],
            createdAt: item.created_at || new Date().toISOString(),
         }))
         setSessions(serverSessions)
         setActiveSessionId(serverSessions.length > 0 ? serverSessions[0].id : null)
      } catch (e) {
         console.error('Lỗi tải lại conversations theo principal:', e)
         setSessions([])
         setActiveSessionId(null)
      }
   }

   // Resolve the current user once on mount (login required to chat). When
   // authenticated, load that principal's conversations; otherwise show nothing.
   useEffect(() => {
      apiGet<UserProfile>('/api/v1/auth/me')
         .then((data) => {
            const resolved: UserProfile | null = data && data.username ? data : null
            setUser(resolved)
            localStorage.removeItem('rag_sessions')
            if (resolved) {
               reloadConversationsForPrincipal()
            } else {
               setSessions([])
               setActiveSessionId(null)
            }
         })
         .catch(() => setUser(null))
      // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [])

   // Handle login: adopt the profile, then rebuild the sidebar from the server
   // for the now-authenticated principal (guest conversations were claimed).
   const handleLoginSuccess = (u: UserProfile) => {
      setUser(u)
      localStorage.removeItem('rag_sessions')
      reloadConversationsForPrincipal()
   }

   // Handle logout: clear identity and wipe the cached sidebar completely.
   const handleLogout = () => {
      setUser(null)
      localStorage.removeItem('rag_sessions')
      setSessions([])
      setActiveSessionId(null)
      clearMessages()
   }

   // 2. Save sessions to localStorage when updated
   useEffect(() => {
      if (sessions.length > 0) {
         localStorage.setItem('rag_sessions', JSON.stringify(sessions))
      }
   }, [sessions])

   // 3. Sync messages from hook to active session
   useEffect(() => {
      if (!activeSessionId) return

      startTransition(() => {
         setSessions((prev) =>
            prev.map((s) => {
               if (s.id !== activeSessionId) return s

               let newTitle = s.title
               if (
                  (s.title === 'Cuộc hội thoại mới' || s.title === 'Cuộc trò chuyện mới') &&
                  messages.length > 0
               ) {
                  const firstUserMsg = messages.find((m) => m.role === 'user')
                  if (firstUserMsg) {
                     newTitle = firstUserMsg.content.slice(0, 30)
                     if (firstUserMsg.content.length > 30) newTitle += '...'
                     apiPatch(`/api/v1/conversations/${activeSessionId}`, {
                        title: newTitle,
                     }).catch(() => {})
                  }
               }

               return {
                  ...s,
                  messages: messages,
                  title: newTitle,
               }
            }),
         )
      })
   }, [messages, activeSessionId])

   const handleSelectSession = async (sessionId: string) => {
      setActiveSessionId(sessionId)
      const targetSession = sessions.find((session) => session.id === sessionId)
      if (targetSession && targetSession.messages && targetSession.messages.length > 0) {
         setMessages(targetSession.messages)
      } else {
         clearMessages()
      }

      try {
         const data = await apiGet<ServerConversationDetail>(`/api/v1/conversations/${sessionId}`)
         if (data && Array.isArray(data.messages)) {
            const loadedMessages = data.messages.map((m) => ({
               id: m.id,
               role: m.role === 'user' ? ('user' as const) : ('assistant' as const),
               content: m.content,
               sources: m.citations
                  ? m.citations.map((c) => ({
                       id: c.unit_id,
                       title: c.citation_label,
                       citation_label: c.citation_label,
                       document_id: c.document_id,
                       deep_link: c.deep_link,
                       ordinal: c.ordinal,
                       content: '',
                    }))
                  : [],
               intent: m.metadata?.intent,
               retrieval_mode: m.metadata?.retrieval_mode,
               cannot_answer: m.metadata?.cannot_answer,
               insufficiency_message: m.metadata?.insufficiency_message,
               temporal_notes: m.explanation?.temporal_notes || [],
               reasoning_paths: m.explanation?.reasoning_paths || [],
               timestamp: m.created_at || new Date().toISOString(),
            }))
            setMessages(loadedMessages)
            setSessions((prev) =>
               prev.map((s) =>
                  s.id === sessionId
                     ? { ...s, messages: loadedMessages, title: data.title || s.title }
                     : s,
               ),
            )
         }
      } catch (e) {
         console.error('Lỗi fetch chi tiết conversation:', e)
      }
   }

   // 5. Scroll to bottom
   const scrollToBottom = () => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
   }

   useEffect(() => {
      scrollToBottom()
   }, [messages])

   // 6. Textarea auto-resize
   useEffect(() => {
      if (textareaRef.current) {
         textareaRef.current.style.height = 'auto'
         textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`
      }
   }, [inputText])

   // 7. Handlers
   const handleNewChat = () => {
      const newId = crypto.randomUUID()
      const newSession: ChatSession = {
         id: newId,
         title: 'Cuộc hội thoại mới',
         messages: [],
         createdAt: new Date().toISOString(),
      }
      setSessions((prev) => [newSession, ...prev])
      setActiveSessionId(newId)
      clearMessages()
      setInputText('')
   }

   const handleDeleteSession = async (id: string) => {
      try {
         await apiDelete(`/api/v1/conversations/${id}`)
      } catch {}

      const updated = sessions.filter((s) => s.id !== id)
      setSessions(updated)

      if (activeSessionId === id) {
         if (updated.length > 0) {
            handleSelectSession(updated[0].id)
         } else {
            const newId = crypto.randomUUID()
            const newSession: ChatSession = {
               id: newId,
               title: 'Cuộc hội thoại mới',
               messages: [],
               createdAt: new Date().toISOString(),
            }
            setSessions([newSession])
            setActiveSessionId(newId)
            clearMessages()
         }
      }
   }

   const handleDeleteAllSessions = () => {
      localStorage.removeItem('rag_sessions')
      const newId = crypto.randomUUID()
      const newSession: ChatSession = {
         id: newId,
         title: 'Cuộc hội thoại mới',
         messages: [],
         createdAt: new Date().toISOString(),
      }
      setSessions([newSession])
      setActiveSessionId(newId)
      clearMessages()
   }

   const handleSend = () => {
      if (!user) {
         setShowAuth(true)
         return
      }
      if (!inputText.trim() || isStreaming) return

      let targetSessionId = activeSessionId
      if (!targetSessionId) {
         targetSessionId = crypto.randomUUID()
         const newSession: ChatSession = {
            id: targetSessionId,
            title: 'Cuộc hội thoại mới',
            messages: [],
            createdAt: new Date().toISOString(),
         }
         setSessions((prev) => [newSession, ...prev])
         setActiveSessionId(targetSessionId)
      }

      const textToSend = inputText
      setInputText('')
      // ChatSession.id chính là conversation_id gửi lên server (Plan 19 §5).
      sendMessage(textToSend, targetSessionId, messages)
   }

   const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
         e.preventDefault()
         handleSend()
      }
   }

   const handleChipClick = (promptText: string) => {
      setInputText(promptText)
      textareaRef.current?.focus()
   }

   // Reusable Input Form Component rendering to keep layout unified
   const renderInputBox = () => {
      return (
         <div className="relative flex flex-col w-full rounded-3xl border border-zinc-200 dark:border-zinc-800 bg-[#f4f4f4] dark:bg-[#2f2f2f] focus-within:border-zinc-300 dark:focus-within:border-zinc-700 transition-colors shadow-2xs overflow-hidden">
            <div className="flex items-center pl-4 pr-2.5 py-1.5">
               {/* Plus Button */}
               <button
                  className="p-2 -ml-1 text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-200/50 dark:hover:bg-zinc-800 rounded-full cursor-pointer transition-colors"
                  title="Đính kèm"
               >
                  <Plus size={20} />
               </button>

               {/* Textarea Input */}
               <textarea
                  ref={textareaRef}
                  rows={1}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={user ? 'Ask anything' : 'Đăng nhập để bắt đầu trò chuyện'}
                  className="flex-1 max-h-[180px] min-h-[40px] py-2 px-3 text-sm bg-transparent border-0 outline-hidden resize-none placeholder-zinc-400 dark:placeholder-zinc-500 text-zinc-900 dark:text-zinc-150 leading-relaxed font-sans focus:ring-0"
               />

               {/* Send button */}
               <div className="flex items-center gap-1.5 shrink-0 ml-1">
                  <button
                     onClick={handleSend}
                     disabled={!inputText.trim() || isStreaming}
                     className={`p-2.5 rounded-full flex items-center justify-center transition-all ${
                        inputText.trim() && !isStreaming
                           ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 shadow-md cursor-pointer'
                           : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-650 cursor-not-allowed'
                     }`}
                     title={!user ? 'Đăng nhập để gửi câu hỏi' : 'Gửi câu hỏi'}
                  >
                     <ArrowUp size={16} strokeWidth={2.5} />
                  </button>
               </div>
            </div>
         </div>
      )
   }

   const isEmpty = messages.length === 0

   return (
      <div className="flex w-screen h-screen overflow-hidden bg-background text-foreground font-sans antialiased">
         {/* Sidebar */}
         <Sidebar
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            onDeleteSession={handleDeleteSession}
            onDeleteAllSessions={handleDeleteAllSessions}
            isOpen={sidebarOpen}
            onToggle={() => setSidebarOpen(!sidebarOpen)}
            user={user ?? null}
            onOpenAuth={() => setShowAuth(true)}
         />

         {/* Auth modal (login required to chat) */}
         <AuthModal
            isOpen={showAuth}
            onClose={() => setShowAuth(false)}
            user={user ?? null}
            onLoginSuccess={handleLoginSuccess}
            onLogout={handleLogout}
         />

         {/* Sidebar Backdrop Overlay on Mobile */}
         {sidebarOpen && (
            <div
               onClick={() => setSidebarOpen(false)}
               className="md:hidden fixed inset-0 z-35 bg-black/40 backdrop-blur-xs transition-opacity duration-300 cursor-pointer"
            />
         )}

         {/* Main Container */}
         <div className="flex-1 flex flex-col h-full bg-background relative overflow-hidden">
            {/* Top Minimal Header */}
            <header className="h-14 flex items-center justify-between px-4 select-none z-10 flex-shrink-0">
               <div className="flex items-center gap-2">
                  {!sidebarOpen && (
                     <button
                        onClick={() => setSidebarOpen(true)}
                        className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer transition-colors"
                        title="Mở sidebar"
                     >
                        <PanelLeft size={19} />
                     </button>
                  )}
                  {!sidebarOpen && (
                     <span className="font-semibold text-sm text-zinc-800 dark:text-zinc-200 select-none ml-1">
                        ChatLegal
                     </span>
                  )}
               </div>

               <div className="flex items-center gap-3">
                  <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-xs font-medium cursor-pointer transition-colors">
                     <Share2 size={13} />
                     <span>Share</span>
                  </button>
                  <button className="p-1.5 rounded-full border border-border hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-zinc-500 cursor-pointer transition-colors">
                     <MoreHorizontal size={14} />
                  </button>
               </div>
            </header>

            {/* Conversation Content Area */}
            <div className="flex-1 overflow-y-auto px-4 md:px-0 flex flex-col">
               {isEmpty ? (
                  /* Welcome / Centered Empty State */
                  <div className="flex-1 flex flex-col justify-center items-center px-4 max-w-3xl mx-auto w-full -mt-14 select-none animate-in fade-in duration-300">
                     <h2 className="text-[28px] md:text-[32px] font-medium tracking-tight text-zinc-800 dark:text-zinc-100 mb-6 text-center leading-tight">
                        What’s on your mind today?
                     </h2>

                     {/* Centered Input Box */}
                     <div className="w-full">{renderInputBox()}</div>

                     {/* Suggested quick chips directly below centered input box */}
                     <div className="flex flex-wrap justify-center gap-2 mt-4">
                        <button
                           onClick={() =>
                              handleChipClick(
                                 'Tóm tắt các điểm mới nổi bật trong Luật Doanh nghiệp hiện hành.',
                              )
                           }
                           className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-border bg-card hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-xs text-zinc-600 dark:text-zinc-400 font-medium cursor-pointer transition-all active:scale-95 shadow-3xs"
                        >
                           <ImageIcon size={12} className="text-zinc-450 dark:text-zinc-500" />
                           <span>Phân tích văn bản</span>
                        </button>
                        <button
                           onClick={() =>
                              handleChipClick(
                                 'Hãy soạn thảo một Thỏa thuận bảo mật thông tin (NDA) mẫu ngắn gọn.',
                              )
                           }
                           className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-border bg-card hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-xs text-zinc-600 dark:text-zinc-400 font-medium cursor-pointer transition-all active:scale-95 shadow-3xs"
                        >
                           <PenLine size={12} className="text-zinc-450 dark:text-zinc-500" />
                           <span>Soạn thảo hợp đồng</span>
                        </button>
                        <button
                           onClick={() =>
                              handleChipClick(
                                 'Giải thích mức giảm trừ gia cảnh thuế TNCN hiện hành tại Việt Nam.',
                              )
                           }
                           className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-border bg-card hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-xs text-zinc-600 dark:text-zinc-400 font-medium cursor-pointer transition-all active:scale-95 shadow-3xs"
                        >
                           <Globe size={12} className="text-zinc-450 dark:text-zinc-500" />
                           <span>Tra cứu pháp lý</span>
                        </button>
                     </div>
                  </div>
               ) : (
                  /* Active Message List */
                  <div className="max-w-3xl mx-auto w-full pt-4 pb-36">
                     <div className="space-y-4">
                        {messages.map((msg, index) => (
                           <MessageItem
                              key={msg.id}
                              message={msg}
                              isLast={index === messages.length - 1}
                              isStreaming={isStreaming}
                           />
                        ))}
                        <div ref={messagesEndRef} />
                     </div>
                  </div>
               )}
            </div>

            {/* Floating Input Box in Bottom Center (Only displayed when there are messages) */}
            {!isEmpty && (
               <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/95 to-transparent px-4 pb-6 pt-4">
                  <div className="max-w-3xl mx-auto w-full">{renderInputBox()}</div>
               </div>
            )}

            {/* Disclaimer Footer (Persistent at the very bottom in both modes) */}
            <div className="w-full flex justify-center pb-2.5 select-none bg-transparent">
               <p className="text-[10px] text-zinc-400 dark:text-zinc-550 text-center font-medium">
                  ChatLegal can make mistakes. Check important info.
               </p>
            </div>
         </div>
      </div>
   )
}
