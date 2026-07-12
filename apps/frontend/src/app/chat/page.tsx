'use client'

import React, { useState, useEffect, useRef } from 'react'
import { Sidebar } from '@/components/layout/Sidebar'
import { MessageItem } from '@/components/chat/MessageItem'
import { useChatStream } from '@/hooks/useChatStream'
import { ChatSession, Message } from '@/types/chat'
import {
   Plus,
   ArrowUp,
   Share2,
   MoreHorizontal,
   PanelLeft,
   Image as ImageIcon,
   PenLine,
   Globe,
   CalendarDays,
   X,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export default function ChatPage() {
   const [sessions, setSessions] = useState<ChatSession[]>([])
   const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
   const [inputText, setInputText] = useState('')
   const [sidebarOpen, setSidebarOpen] = useState(true)
   const [temporalDate, setTemporalDate] = useState<string>('')  // Ngày tra cứu hiệu lực
   const [showDatePicker, setShowDatePicker] = useState(false)

   // Custom hook for SSE Streaming
   const { messages, setMessages, isStreaming, sendMessage, clearMessages } = useChatStream([])

   const messagesEndRef = useRef<HTMLDivElement>(null)
   const textareaRef = useRef<HTMLTextAreaElement>(null)

   // 1. Load sessions from localStorage on mount
   useEffect(() => {
      const saved = localStorage.getItem('rag_sessions')
      if (saved) {
         try {
            const parsed = JSON.parse(saved)
            setSessions(parsed)
            if (parsed.length > 0) {
               setActiveSessionId(parsed[0].id)
            }
         } catch (e) {
            console.error('Lỗi load sessions từ localStorage:', e)
         }
      } else {
         const defaultId = crypto.randomUUID()
         const defaultSession: ChatSession = {
            id: defaultId,
            title: 'Cuộc hội thoại mới',
            messages: [],
            createdAt: new Date().toISOString(),
         }
         setSessions([defaultSession])
         setActiveSessionId(defaultId)
      }
   }, [])

   // 2. Save sessions to localStorage when updated
   useEffect(() => {
      if (sessions.length > 0) {
         localStorage.setItem('rag_sessions', JSON.stringify(sessions))
      }
   }, [sessions])

   // 3. Sync messages from hook to active session
   useEffect(() => {
      if (!activeSessionId) return

      setSessions((prev) =>
         prev.map((s) => {
            if (s.id !== activeSessionId) return s

            let newTitle = s.title
            if (s.title === 'Cuộc hội thoại mới' && messages.length > 0) {
               const firstUserMsg = messages.find((m) => m.role === 'user')
               if (firstUserMsg) {
                  newTitle = firstUserMsg.content.slice(0, 30)
                  if (firstUserMsg.content.length > 30) newTitle += '...'
               }
            }

            return {
               ...s,
               messages: messages,
               title: newTitle,
            }
         }),
      )
   }, [messages, activeSessionId])

   // 4. Load messages of active session when active session changes
   useEffect(() => {
      if (activeSessionId) {
         const targetSession = sessions.find((s) => s.id === activeSessionId)
         if (targetSession) {
            setMessages(targetSession.messages)
         }
      } else {
         clearMessages()
      }
   }, [activeSessionId])

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

   const handleDeleteSession = (id: string) => {
      const updated = sessions.filter((s) => s.id !== id)
      setSessions(updated)

      if (activeSessionId === id) {
         if (updated.length > 0) {
            setActiveSessionId(updated[0].id)
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
      if (!inputText.trim() || isStreaming) return
      const textToSend = inputText
      setInputText('')
      sendMessage(textToSend, messages, temporalDate || undefined)
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
            {/* Temporal date indicator */}
            {temporalDate && (
               <div className="flex items-center gap-2 px-4 pt-2">
                  <CalendarDays size={12} className="text-primary" />
                  <span className="text-xs text-primary">Tra cứu theo ngày: {new Date(temporalDate).toLocaleDateString('vi-VN')}</span>
                  <button onClick={() => setTemporalDate('')} className="ml-auto text-muted-foreground hover:text-foreground">
                     <X size={11} />
                  </button>
               </div>
            )}

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
                  placeholder="Ask anything"
                  className="flex-1 max-h-[180px] min-h-[40px] py-2 px-3 text-sm bg-transparent border-0 outline-hidden resize-none placeholder-zinc-400 dark:placeholder-zinc-500 text-zinc-900 dark:text-zinc-150 leading-relaxed font-sans focus:ring-0"
               />

               {/* Date picker toggle */}
               <div className="relative">
                  <button
                     onClick={() => setShowDatePicker(!showDatePicker)}
                     title="Chọn ngày tra cứu hiệu lực"
                     className={`p-2 rounded-full transition-colors cursor-pointer ${
                        temporalDate
                           ? 'text-primary bg-primary/10'
                           : 'text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200/50 dark:hover:bg-zinc-800'
                     }`}
                  >
                     <CalendarDays size={16} />
                  </button>
                  {showDatePicker && (
                     <div className="absolute bottom-10 right-0 bg-card border border-border rounded-xl shadow-lg p-3 z-50 w-64">
                        <p className="text-xs font-medium mb-2 text-foreground">Tra cứu văn bản theo ngày hiệu lực</p>
                        <input
                           type="date"
                           value={temporalDate}
                           max={new Date().toISOString().split('T')[0]}
                           onChange={(e) => {
                              setTemporalDate(e.target.value)
                              setShowDatePicker(false)
                           }}
                           className="w-full text-xs border border-border rounded-lg px-2 py-1.5 bg-background text-foreground"
                        />
                        {temporalDate && (
                           <button
                              onClick={() => { setTemporalDate(''); setShowDatePicker(false) }}
                              className="mt-2 w-full text-xs text-muted-foreground hover:text-foreground"
                           >
                              Xóa ngày đã chọn
                           </button>
                        )}
                     </div>
                  )}
               </div>

               {/* Send button */}
               <div className="flex items-center gap-1.5 flex-shrink-0 ml-1">
                  <button
                     onClick={handleSend}
                     disabled={!inputText.trim() || isStreaming}
                     className={`p-2.5 rounded-full flex items-center justify-center transition-all ${
                        inputText.trim() && !isStreaming
                           ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 shadow-md cursor-pointer'
                           : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-650 cursor-not-allowed'
                     }`}
                     title="Gửi câu hỏi"
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
            onSelectSession={setActiveSessionId}
            onNewChat={handleNewChat}
            onDeleteSession={handleDeleteSession}
            onDeleteAllSessions={handleDeleteAllSessions}
            isOpen={sidebarOpen}
            onToggle={() => setSidebarOpen(!sidebarOpen)}
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
