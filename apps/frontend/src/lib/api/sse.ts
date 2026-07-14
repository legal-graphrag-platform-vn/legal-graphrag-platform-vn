export type SseEventName = 'metadata' | 'token' | 'citation' | 'error' | 'done'

export interface ParsedSseEvent {
   event: SseEventName
   data: Record<string, unknown>
}

export class SseProtocolError extends Error {
   constructor(message: string) {
      super(message)
      this.name = 'SseProtocolError'
   }
}

export class SseParser {
   private buffer = ''
   private eventName: string | null = null
   private dataLines: string[] = []

   push(chunk: string): ParsedSseEvent[] {
      this.buffer += chunk
      const lines = this.buffer.split(/\r?\n/)
      this.buffer = lines.pop() ?? ''
      const events: ParsedSseEvent[] = []

      for (const line of lines) {
         if (line === '') {
            const event = this.flushEvent()
            if (event) events.push(event)
         } else if (line.startsWith('event:')) {
            this.eventName = line.slice(6).trim()
         } else if (line.startsWith('data:')) {
            this.dataLines.push(line.slice(5).trimStart())
         }
      }
      return events
   }

   finish(): ParsedSseEvent[] {
      if (this.buffer) {
         const trailing = this.buffer
         this.buffer = ''
         if (trailing.startsWith('data:')) this.dataLines.push(trailing.slice(5).trimStart())
      }
      const event = this.flushEvent()
      return event ? [event] : []
   }

   private flushEvent(): ParsedSseEvent | null {
      if (!this.eventName && this.dataLines.length === 0) return null
      const event = this.eventName
      const rawData = this.dataLines.join('\n')
      this.eventName = null
      this.dataLines = []

      if (!isEventName(event))
         throw new SseProtocolError(`Unsupported SSE event: ${event ?? 'missing'}`)
      try {
         const data = JSON.parse(rawData) as unknown
         if (!data || typeof data !== 'object' || Array.isArray(data)) {
            throw new SseProtocolError(`SSE ${event} data must be an object`)
         }
         return { event, data: data as Record<string, unknown> }
      } catch (error) {
         if (error instanceof SseProtocolError) throw error
         throw new SseProtocolError(`Invalid JSON for SSE event: ${event}`)
      }
   }
}

function isEventName(value: string | null): value is SseEventName {
   return (
      value === 'metadata' ||
      value === 'token' ||
      value === 'citation' ||
      value === 'error' ||
      value === 'done'
   )
}
