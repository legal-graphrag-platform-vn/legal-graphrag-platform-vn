'use client'

import { useEffect, useRef, useState } from 'react'
import { apiStream } from '@/lib/api/client'
import { SseParser, SseProtocolError, type ParsedSseEvent } from '@/lib/api/sse'
import type { Message, ReasoningPath, ResolvedReference, Source } from '@/types/chat'

export function useChatStream(initialMessages: Message[] = []) {
   const [messages, setMessages] = useState<Message[]>(initialMessages)
   const [isStreaming, setIsStreaming] = useState(false)
   const abortRef = useRef<AbortController | null>(null)
   const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

   useEffect(
      () => () => {
         abortRef.current?.abort()
         if (timerRef.current) clearInterval(timerRef.current)
      },
      [],
   )

   const sendMessage = async (
      text: string,
      conversationId: string,
      currentMessages: Message[],
      queryDate?: string,
   ) => {
      if (!text.trim() || isStreaming) return

      // client_turn_id ổn định trong suốt lần gửi này (kể cả transport retry),
      // để server idempotent hoá turn và không gọi provider lần hai (Plan 19 §5).
      const clientTurnId = crypto.randomUUID()
      const userMessage: Message = {
         id: crypto.randomUUID(),
         role: 'user',
         content: text,
         timestamp: new Date().toISOString(),
         client_turn_id: clientTurnId,
      }
      const assistantId = crypto.randomUUID()
      setMessages([
         ...currentMessages,
         userMessage,
         {
            id: assistantId,
            role: 'assistant',
            content: '',
            sources: [],
            timestamp: new Date().toISOString(),
         },
      ])
      setIsStreaming(true)

      let rawText = ''
      let displayed = ''
      let streamDone = false
      const controller = new AbortController()
      abortRef.current = controller
      timerRef.current = setInterval(() => {
         const remaining = rawText.length - displayed.length
         if (remaining > 0) {
            const count = remaining > 40 ? 5 : remaining > 20 ? 3 : remaining > 8 ? 2 : 1
            displayed += rawText.slice(displayed.length, displayed.length + count)
            updateAssistant(setMessages, assistantId, { content: displayed })
         } else if (streamDone) {
            clearActiveTimer(timerRef)
            setIsStreaming(false)
         }
      }, 20)

      try {
         // Không gửi local history — server sở hữu context (Plan 19 §5).
         const body: Record<string, unknown> = {
            conversation_id: conversationId,
            client_turn_id: clientTurnId,
            message: text,
         }
         if (queryDate) body.query_date = queryDate

         const response = await apiStream('/api/v1/chat', body, controller.signal)
         if (!response.ok) {
            let errorMsg = `Lỗi hệ thống (${response.status})`
            try {
               const errJson = await response.json()
               if (errJson && errJson.message) {
                  errorMsg = errJson.message
               }
            } catch {}
            throw new Error(errorMsg)
         }
         const reader = response.body?.getReader()
         if (!reader) throw new SseProtocolError('Response does not provide an SSE stream')

         const decoder = new TextDecoder()
         const parser = new SseParser()
         let doneReceived = false
         while (true) {
            const result = await reader.read()
            if (result.done) break
            for (const event of parser.push(decoder.decode(result.value, { stream: true }))) {
               const outcome = applyEvent(event, assistantId, setMessages)
               rawText += outcome.token
               if (outcome.done) doneReceived = true
               if (outcome.error) throw new Error(outcome.error)
            }
         }
         for (const event of parser.finish()) {
            const outcome = applyEvent(event, assistantId, setMessages)
            rawText += outcome.token
            if (outcome.done) doneReceived = true
            if (outcome.error) throw new Error(outcome.error)
         }
         if (!doneReceived) throw new SseProtocolError('SSE stream ended without done event')
         streamDone = true
      } catch (error) {
         clearActiveTimer(timerRef)
         setIsStreaming(false)
         if (controller.signal.aborted) return
         const message = error instanceof Error ? error.message : 'Không thể kết nối server'
         updateAssistant(setMessages, assistantId, {
            content: `⚠️ **Không thể hoàn tất câu trả lời**: ${message}`,
            error: message,
         })
      } finally {
         abortRef.current = null
      }
   }

   const clearMessages = () => setMessages([])
   return { messages, setMessages, isStreaming, sendMessage, clearMessages }
}

function applyEvent(
   event: ParsedSseEvent,
   assistantId: string,
   setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
): { token: string; done: boolean; error?: string } {
   if (event.event === 'metadata') {
      updateAssistant(setMessages, assistantId, {
         sources: mapSources(event.data.sources),
         intent: stringValue(event.data.intent),
         retrieval_mode: stringValue(event.data.retrieval_mode),
         resolution_status: stringValue(event.data.resolution_status),
         cannot_answer: event.data.cannot_answer === true,
         insufficiency_message: stringValue(event.data.insufficiency_message),
         resolved_references: resolvedReferences(event.data.resolved_references),
         relation_goal: stringValue(event.data.relation_goal),
      })
   } else if (event.event === 'clarification') {
      // Turn cần làm rõ: không có source cards; câu hỏi tới qua token stream.
      updateAssistant(setMessages, assistantId, { kind: 'clarification', sources: [] })
   } else if (event.event === 'done' && stringValue(event.data.status) === 'processing') {
      // Turn trùng đang được xử lý ở nơi khác — báo người dùng thử lại.
      updateAssistant(setMessages, assistantId, {
         kind: 'processing',
         content: 'Câu hỏi đang được xử lý, vui lòng thử lại sau giây lát.',
      })
   } else if (event.event === 'citation') {
      const unitId = stringValue(event.data.unit_id)
      const deepLink = stringValue(event.data.deep_link)
      const ordinal = numberValue(event.data.ordinal)
      setMessages((previous) =>
         previous.map((message) =>
            message.id === assistantId
               ? {
                    ...message,
                    sources: message.sources?.map((source) =>
                       source.id === unitId ? { ...source, deep_link: deepLink, ordinal } : source,
                    ),
                 }
               : message,
         ),
      )
   } else if (event.event === 'explanation') {
      updateAssistant(setMessages, assistantId, {
         temporal_notes: stringArray(event.data.temporal_notes),
         reasoning_paths: reasoningPaths(event.data.reasoning_paths),
      })
   }
   return {
      token: event.event === 'token' ? (stringValue(event.data.content) ?? '') : '',
      done: event.event === 'done',
      error: event.event === 'error' ? (stringValue(event.data.message) ?? 'Lỗi SSE') : undefined,
   }
}

function mapSources(value: unknown): Source[] {
   if (!Array.isArray(value)) return []
   return value.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const source = item as Record<string, unknown>
      const id = stringValue(source.id)
      if (!id) return []
      return [
         {
            id,
            title: stringValue(source.citation_label) ?? id,
            content: stringValue(source.content_raw) ?? '',
            citation_label: stringValue(source.citation_label),
            label: labelValue(source.label),
            document_id: stringValue(source.document_id),
            document_number: stringValue(source.document_number),
            article_id: stringValue(source.article_id),
            clause_id: stringValue(source.clause_id),
            effective_from: stringValue(source.effective_from),
            effective_to: stringValue(source.effective_to),
            final_score: numberValue(source.final_score),
            deep_link: stringValue(source.deep_link),
         },
      ]
   })
}

function updateAssistant(
   setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
   assistantId: string,
   patch: Partial<Message>,
) {
   setMessages((previous) =>
      previous.map((message) => (message.id === assistantId ? { ...message, ...patch } : message)),
   )
}

function stringValue(value: unknown): string | undefined {
   return typeof value === 'string' ? value : undefined
}

function numberValue(value: unknown): number | undefined {
   return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function labelValue(value: unknown): Source['label'] {
   return value === 'Article' || value === 'Clause' || value === 'Point' ? value : undefined
}

function stringArray(value: unknown): string[] {
   return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === 'string')
      : []
}

function reasoningPaths(value: unknown): ReasoningPath[] {
   if (!Array.isArray(value)) return []
   return value.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const path = item as Record<string, unknown>
      const pathId = stringValue(path.path_id)
      if (!pathId) return []
      return [
         {
            path_id: pathId,
            description: stringValue(path.description) || '',
            nodes: stringArray(path.nodes),
         },
      ]
   })
}

function resolvedReferences(value: unknown): ResolvedReference[] {
   if (!Array.isArray(value)) return []
   return value.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const reference = item as Record<string, unknown>
      const nodeId = stringValue(reference.node_id)
      const nodeType = stringValue(reference.node_type)
      const method = stringValue(reference.resolution_method)
      const source = stringValue(reference.source)
      if (
         !nodeId ||
         !['Document', 'Article', 'Clause', 'Point'].includes(nodeType || '') ||
         !['EXACT_STRUCTURAL_LOOKUP', 'GROUNDED_HISTORY_FOCUS'].includes(method || '') ||
         !['CURRENT_MESSAGE', 'GROUNDED_HISTORY', 'PENDING_CLARIFICATION'].includes(source || '')
      )
         return []
      return [
         {
            mention: stringValue(reference.mention) || '',
            node_id: nodeId,
            node_type: nodeType as ResolvedReference['node_type'],
            label: stringValue(reference.label) || nodeId,
            document_id: stringValue(reference.document_id) || '',
            resolution_method: method as ResolvedReference['resolution_method'],
            source: source as ResolvedReference['source'],
         },
      ]
   })
}

function clearActiveTimer(timerRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>) {
   if (timerRef.current) clearInterval(timerRef.current)
   timerRef.current = null
}
