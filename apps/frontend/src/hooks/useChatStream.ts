import { useState } from 'react'
import { Message, Source } from '../types/chat'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'

export function useChatStream(initialMessages: Message[] = []) {
   const [messages, setMessages] = useState<Message[]>(initialMessages)
   const [isStreaming, setIsStreaming] = useState(false)

   const sendMessage = async (text: string, currentMessages: Message[]) => {
      if (!text.trim() || isStreaming) return

      // 1. Create and add user message
      const userMessage: Message = {
         id: crypto.randomUUID(),
         role: 'user',
         content: text,
         timestamp: new Date().toISOString(),
      }

      const updatedMessages = [...currentMessages, userMessage]
      setMessages(updatedMessages)
      setIsStreaming(true)

      // 2. Add empty assistant message that will be updated in real-time
      const assistantMessageId = crypto.randomUUID()
      const assistantMessage: Message = {
         id: assistantMessageId,
         role: 'assistant',
         content: '',
         sources: [],
         timestamp: new Date().toISOString(),
      }

      setMessages((prev) => [...prev, assistantMessage])

      // Variables to manage smooth typewriter effect
      let rawTextFromServer = ''
      let displayedContent = ''
      let streamFinished = false
      let sourcesList: Source[] = []

      // 3. Start typewriter interval (runs every 20ms)
      const typewriterInterval = setInterval(() => {
         const remainingLength = rawTextFromServer.length - displayedContent.length

         if (remainingLength > 0) {
            // Dynamic speed control: if network is ahead, print more characters at once
            const charsToAppend =
               remainingLength > 40 ? 5 : remainingLength > 20 ? 3 : remainingLength > 8 ? 2 : 1

            displayedContent += rawTextFromServer.slice(
               displayedContent.length,
               displayedContent.length + charsToAppend,
            )

            setMessages((prev) =>
               prev.map((msg) =>
                  msg.id === assistantMessageId ? { ...msg, content: displayedContent } : msg,
               ),
            )
         } else if (streamFinished) {
            // Stream completed and typewriter fully caught up
            clearInterval(typewriterInterval)
            setIsStreaming(false)
         }
      }, 20)

      try {
         // 4. Request SSE stream from Flask server
         const response = await fetch(`${API_URL}/api/chat`, {
            method: 'POST',
            headers: {
               'Content-Type': 'application/json',
            },
            body: JSON.stringify({
               message: text,
               history: currentMessages.map((msg) => ({
                  role: msg.role,
                  content: msg.content,
               })),
            }),
         })

         if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`)
         }

         const reader = response.body?.getReader()
         if (!reader) {
            throw new Error('ReadableStream not supported or no body returned')
         }

         const decoder = new TextDecoder()
         let buffer = ''

         while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')

            // Keep the last partial line in the buffer
            buffer = lines.pop() || ''

            for (const line of lines) {
               const trimmed = line.trim()
               if (!trimmed) continue

               if (trimmed.startsWith('data: ')) {
                  const dataStr = trimmed.slice(6)
                  if (dataStr === '[DONE]') {
                     break
                  }

                  try {
                     const data = JSON.parse(dataStr)
                     if (data.type === 'metadata' && data.sources) {
                        sourcesList = data.sources
                        setMessages((prev) =>
                           prev.map((msg) =>
                              msg.id === assistantMessageId
                                 ? { ...msg, sources: sourcesList }
                                 : msg,
                           ),
                        )
                     } else if (data.type === 'content' && data.content) {
                        // Accumulate incoming text in background; typewriter interval will animate it
                        rawTextFromServer += data.content
                     }
                  } catch (err) {
                     console.warn('Error parsing JSON chunk:', err, trimmed)
                  }
               }
            }
         }

         // Signal stream completion; interval will stop once queue is empty
         streamFinished = true
      } catch (error) {
         console.error('Error during streaming:', error)
         clearInterval(typewriterInterval)
         setIsStreaming(false)

         // Update assistant message with error state immediately
         setMessages((prev) =>
            prev.map((msg) =>
               msg.id === assistantMessageId
                  ? {
                       ...msg,
                       content:
                          '❌ Có lỗi xảy ra trong quá trình kết nối với server. Vui lòng thử lại sau.',
                    }
                  : msg,
            ),
         )
      }
   }

   const clearMessages = () => {
      setMessages([])
   }

   return {
      messages,
      setMessages,
      isStreaming,
      sendMessage,
      clearMessages,
   }
}
