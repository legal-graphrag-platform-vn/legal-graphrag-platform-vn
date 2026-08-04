import { describe, expect, it } from 'vitest'
import { SseParser, SseProtocolError } from './sse'

describe('SseParser', () => {
   it('parses fragmented unicode named events deterministically', () => {
      const parser = new SseParser()

      expect(parser.push('event: token\ndata: {"content":"Xin')).toEqual([])
      expect(parser.push(' chào"}\n\nevent: done\r\ndata: {}\r\n\r\n')).toEqual([
         { event: 'token', data: { content: 'Xin chào' } },
         { event: 'done', data: {} },
      ])
   })

   it('preserves metadata and citation payloads', () => {
      const parser = new SseParser()
      const events = parser.push(
         'event: metadata\ndata: {"sources":[{"id":"art1"}]}\n\n' +
            'event: citation\ndata: {"unit_id":"art1","deep_link":"/explorer?document=doc"}\n\n',
      )

      expect(events[0].event).toBe('metadata')
      expect(events[1].data.deep_link).toBe('/explorer?document=doc')
   })

   it('parses clarification events (Plan 19 §5)', () => {
      const parser = new SseParser()
      const events = parser.push(
         'event: clarification\n' +
            'data: {"mode":"SELECT","question":"Bạn hỏi điều nào?","candidates":[{"candidate_id":"c1","label":"Điều 4"}]}\n\n',
      )

      expect(events[0].event).toBe('clarification')
      expect(events[0].data.mode).toBe('SELECT')
      expect(events[0].data.question).toBe('Bạn hỏi điều nào?')
   })

   it('rejects malformed JSON and unknown events', () => {
      expect(() => new SseParser().push('event: token\ndata: nope\n\n')).toThrow(SseProtocolError)
      expect(() => new SseParser().push('event: legacy\ndata: {}\n\n')).toThrow(
         'Unsupported SSE event',
      )
   })
})
