import { useState } from 'react'
import { Message, Source } from '../types/chat'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/**
 * Parse SSE named-event stream từ FastAPI.
 * Format mới:
 *   event: metadata
 *   data: {"sources":[...],"intent":"factual","retrieval_mode":"mock"}
 *
 *   event: token
 *   data: {"content":"Vốn "}
 *
 *   event: error
 *   data: {"code":"STREAM_ERROR","message":"..."}
 *
 *   event: done
 *   data: {}
 */
export function useChatStream(initialMessages: Message[] = []) {
   const [messages, setMessages] = useState<Message[]>(initialMessages)
   const [isStreaming, setIsStreaming] = useState(false)

   const sendMessage = async (
      text: string,
      currentMessages: Message[],
      temporalDate?: string,
   ) => {
      if (!text.trim() || isStreaming) return

      // 1. Add user message
      const userMessage: Message = {
         id: crypto.randomUUID(),
         role: 'user',
         content: text,
         timestamp: new Date().toISOString(),
      }
      const updatedMessages = [...currentMessages, userMessage]
      setMessages(updatedMessages)
      setIsStreaming(true)

      // 2. Placeholder assistant message
      const assistantId = crypto.randomUUID()
      const assistantMessage: Message = {
         id: assistantId,
         role: 'assistant',
         content: '',
         sources: [],
         timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, assistantMessage])

      // 3. Typewriter buffer
      let rawText = ''
      let displayed = ''
      let streamDone = false

      const typewriterInterval = setInterval(() => {
         const remaining = rawText.length - displayed.length
         if (remaining > 0) {
            const charsToAdd = remaining > 40 ? 5 : remaining > 20 ? 3 : remaining > 8 ? 2 : 1
            displayed += rawText.slice(displayed.length, displayed.length + charsToAdd)
            setMessages((prev) =>
               prev.map((msg) =>
                  msg.id === assistantId ? { ...msg, content: displayed } : msg,
               ),
            )
         } else if (streamDone) {
            clearInterval(typewriterInterval)
            setIsStreaming(false)
         }
      }, 20)

      try {
         // 4. POST đến FastAPI /api/v1/chat
         const body: Record<string, unknown> = {
            message: text,
            history: currentMessages.map((m) => ({ role: m.role, content: m.content })),
         }
         if (temporalDate) body.temporal_date = temporalDate

         const response = await fetch(`${API_URL}/api/v1/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
         })

         if (!response.ok) {
            throw new Error(`HTTP ${response.status}`)
         }

         const reader = response.body?.getReader()
         if (!reader) throw new Error('ReadableStream not supported')

         const decoder = new TextDecoder()
         let buffer = ''
         let currentEvent = ''

         while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
               const trimmed = line.trim()

               // 5. Parse named SSE events
               if (trimmed.startsWith('event: ')) {
                  currentEvent = trimmed.slice(7).trim()
                  continue
               }

               if (!trimmed.startsWith('data: ')) continue

               const dataStr = trimmed.slice(6)

               // Backward compat với Flask [DONE]
               if (dataStr === '[DONE]') {
                  streamDone = true
                  break
               }

               try {
                  const payload = JSON.parse(dataStr)

                  if (currentEvent === 'metadata') {
                     // Map RetrievedUnitDTO → Source (backward compat)
                     const sources: Source[] = (payload.sources ?? []).map(
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        (s: any) => ({
                           id: s.id,
                           title: s.citation_label ?? s.id,
                           content: s.content_raw ?? '',
                           citation_label: s.citation_label,
                           label: s.label,
                           document_id: s.document_id,
                           document_number: s.document_number,
                           article_id: s.article_id,
                           clause_id: s.clause_id,
                           effective_from: s.effective_from,
                           effective_to: s.effective_to,
                           final_score: s.final_score,
                        }),
                     )
                     setMessages((prev) =>
                        prev.map((msg) =>
                           msg.id === assistantId
                              ? {
                                   ...msg,
                                   sources,
                                   intent: payload.intent,
                                   retrieval_mode: payload.retrieval_mode,
                                }
                              : msg,
                        ),
                     )
                  } else if (currentEvent === 'token') {
                     // Accumulate — typewriter interval sẽ animate
                     rawText += payload.content ?? ''
                  } else if (currentEvent === 'error') {
                     setMessages((prev) =>
                        prev.map((msg) =>
                           msg.id === assistantId
                              ? {
                                   ...msg,
                                   error: payload.message ?? 'Đã xảy ra lỗi',
                                   content: `❌ ${payload.message ?? 'Đã xảy ra lỗi'}`,
                                }
                              : msg,
                        ),
                     )
                  } else if (currentEvent === 'done') {
                     streamDone = true
                  } else if (!currentEvent) {
                     // Backward compat: Flask format không có named event
                     if (payload.type === 'metadata' && payload.sources) {
                        const sources: Source[] = payload.sources
                        setMessages((prev) =>
                           prev.map((msg) =>
                              msg.id === assistantId ? { ...msg, sources } : msg,
                           ),
                        )
                     } else if (payload.type === 'content' && payload.content) {
                        rawText += payload.content
                     }
                  }
               } catch (err) {
                  console.warn('SSE parse error:', err, trimmed)
               }
            }
         }

         streamDone = true
      } catch (error) {
         console.error('Chat stream error:', error)
         clearInterval(typewriterInterval)
         setIsStreaming(false)
         setMessages((prev) =>
            prev.map((msg) =>
               msg.id === assistantId
                  ? {
                       ...msg,
                       content: '❌ Có lỗi xảy ra khi kết nối server. Vui lòng thử lại.',
                    }
                  : msg,
            ),
         )
      }
   }

   const clearMessages = () => setMessages([])

   return { messages, setMessages, isStreaming, sendMessage, clearMessages }
}
