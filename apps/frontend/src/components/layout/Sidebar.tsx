import { PanelLeftClose, Settings, SquarePen, Trash2, X, BookOpen } from 'lucide-react'
import { useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { ThemeToggle } from './ThemeToggle'
import { ChatSession } from '../../types/chat'

interface SidebarProps {
   sessions: ChatSession[]
   activeSessionId: string | null
   onSelectSession: (id: string) => void
   onNewChat: () => void
   onDeleteSession: (id: string) => void
   onDeleteAllSessions: () => void
   isOpen: boolean
   onToggle: () => void
}

export function Sidebar({
   sessions,
   activeSessionId,
   onSelectSession,
   onNewChat,
   onDeleteSession,
   onDeleteAllSessions,
   isOpen,
   onToggle,
}: SidebarProps) {
   const [showSettings, setShowSettings] = useState(false)
   const pathname = usePathname()
   const router = useRouter()

   return (
      <div
         className={`bg-sidebar border-border flex flex-col justify-between select-none shrink-0 transition-all duration-300 ease-in-out h-full z-40
            fixed inset-y-0 border-r w-[280px]
            md:static md:w-64
            ${
               isOpen
                  ? 'left-0 ml-0'
                  : 'left-[-280px] md:w-0 md:-ml-64 md:border-r-0 overflow-hidden'
            }
         `}
      >
         {/* Top Section */}
         <div className="flex flex-col flex-1 overflow-hidden">
            {/* Header */}
            <div className="p-3.5 flex items-center justify-between">
               <span className="font-semibold text-base tracking-tight text-zinc-900 dark:text-white">
                  ChatLegal
               </span>
               <button
                  onClick={onToggle}
                  className="p-1.5 rounded-lg hover:bg-zinc-200/55 dark:hover:bg-zinc-800 text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
                  title="Đóng sidebar"
               >
                  <PanelLeftClose size={18} />
               </button>
            </div>

            {/* Primary Actions List */}
            <div className="px-2.5 py-1.5 space-y-0.5 text-sm font-medium">
               {/* New Chat */}
               <button
                  onClick={() => { onNewChat(); router.push('/chat') }}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors cursor-pointer ${
                     pathname === '/chat'
                        ? 'bg-zinc-200/60 dark:bg-zinc-800/80 text-zinc-900 dark:text-white'
                        : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800 text-zinc-850 dark:text-zinc-200'
                  }`}
               >
                  <SquarePen size={17} className="text-zinc-600 dark:text-zinc-400" />
                  <span>New chat</span>
               </button>

               {/* Document Explorer */}
               <button
                  onClick={() => router.push('/explorer')}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors cursor-pointer ${
                     pathname?.startsWith('/explorer')
                        ? 'bg-zinc-200/60 dark:bg-zinc-800/80 text-zinc-900 dark:text-white'
                        : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800 text-zinc-850 dark:text-zinc-200'
                  }`}
               >
                  <BookOpen size={17} className="text-zinc-600 dark:text-zinc-400" />
                  <span>Tra cứu văn bản</span>
               </button>
            </div>

            {/* Scrollable Recents Conversations List */}
            <div className="flex-1 overflow-y-auto px-2.5 mt-4 space-y-1">
               <div className="px-3 mb-1 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider dark:text-zinc-550 select-none">
                  Recents
               </div>
               {sessions.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-zinc-400 italic">No recent chats</div>
               ) : (
                  sessions.map((session) => {
                     const isActive = session.id === activeSessionId
                     return (
                        <div
                           key={session.id}
                           className={`group relative flex items-center justify-between rounded-lg transition-colors ${
                              isActive
                                 ? 'bg-zinc-200/60 text-zinc-900 dark:bg-zinc-800/80 dark:text-white'
                                 : 'text-zinc-650 hover:bg-zinc-250/40 dark:text-zinc-300 dark:hover:bg-zinc-800/30'
                           }`}
                        >
                           <button
                              onClick={() => onSelectSession(session.id)}
                              className="flex-1 px-3 py-2 text-left text-sm truncate cursor-pointer pr-8 font-normal"
                           >
                              <span className="truncate block">{session.title}</span>
                           </button>

                           <button
                              onClick={(e) => {
                                 e.stopPropagation()
                                 onDeleteSession(session.id)
                              }}
                              className="absolute right-1.5 opacity-0 group-hover:opacity-100 p-1 rounded-md text-zinc-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/20 transition-all cursor-pointer"
                              title="Xóa cuộc trò chuyện"
                           >
                              <Trash2 size={13} />
                           </button>
                        </div>
                     )
                  })
               )}
            </div>
         </div>

         {/* Sidebar Footer with Settings */}
         <div className="p-3 border-t border-border relative flex items-center gap-2">
            <button
               onClick={() => setShowSettings(!showSettings)}
               className="flex-1 flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-zinc-200/50 dark:hover:bg-zinc-800 text-zinc-850 dark:text-zinc-200 text-left transition-colors cursor-pointer text-sm font-medium"
            >
               <Settings size={17} className="text-zinc-650 dark:text-zinc-400" />
               <span>Settings</span>
            </button>
            <ThemeToggle />

            {/* Settings Modal (Centered on Screen) */}
            {showSettings && (
               <div
                  onClick={() => setShowSettings(false)}
                  className="fixed inset-0 z-55 flex items-center justify-center p-4 bg-black/65 backdrop-blur-xs animate-in fade-in duration-200 cursor-pointer"
               >
                  <div
                     onClick={(e) => e.stopPropagation()}
                     className="relative w-full max-w-md bg-card rounded-2xl shadow-2xl border border-border flex flex-col animate-in fade-in zoom-in-95 duration-200 cursor-default"
                  >
                     {/* Header */}
                     <div className="flex items-center justify-between p-4 border-b border-border">
                        <h3 className="font-semibold text-base text-foreground">Settings</h3>
                        <button
                           onClick={() => setShowSettings(false)}
                           className="p-1 rounded-lg hover:bg-zinc-150/50 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-650 dark:hover:text-zinc-200 transition-colors cursor-pointer"
                           title="Close"
                        >
                           <X size={16} />
                        </button>
                     </div>

                     {/* Content */}
                     <div className="p-5 flex flex-col gap-4">
                        <div className="flex items-center justify-between py-2">
                           <div className="pr-4">
                              <h4 className="text-sm font-medium text-foreground">Xóa dữ liệu</h4>
                              <p className="text-xs text-zinc-400 mt-0.5">
                                 Xóa vĩnh viễn toàn bộ lịch sử trò chuyện
                              </p>
                           </div>
                           <button
                              onClick={() => {
                                 if (
                                    confirm('Bạn có chắc chắn muốn xóa tất cả các cuộc trò chuyện?')
                                 ) {
                                    onDeleteAllSessions()
                                    setShowSettings(false)
                                 }
                              }}
                              className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg cursor-pointer transition-colors shadow-xs shrink-0"
                           >
                              <Trash2 size={13} />
                              <span>Delete all chats</span>
                           </button>
                        </div>
                     </div>
                  </div>
               </div>
            )}
         </div>
      </div>
   )
}
