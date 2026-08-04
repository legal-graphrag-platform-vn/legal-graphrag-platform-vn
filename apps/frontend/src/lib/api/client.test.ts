import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGet, apiPost, apiStream } from './client'

/**
 * Plan 19 §5: mọi request phải gửi kèm cookie principal (`credentials: 'include'`)
 * để server nhận diện owner của conversation.
 */
describe('api client sends principal cookie', () => {
   afterEach(() => {
      vi.restoreAllMocks()
   })

   function mockFetch(): ReturnType<typeof vi.fn> {
      const fetchMock = vi.fn(async () =>
         new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
      )
      vi.stubGlobal('fetch', fetchMock)
      return fetchMock
   }

   it('apiGet includes credentials', async () => {
      const fetchMock = mockFetch()
      await apiGet('/api/v1/health')
      expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' })
   })

   it('apiPost includes credentials', async () => {
      const fetchMock = mockFetch()
      await apiPost('/api/v1/chat', { message: 'hi' })
      expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' })
   })

   it('apiStream includes credentials and does not leak history', async () => {
      const fetchMock = mockFetch()
      const body = { conversation_id: 'conv', client_turn_id: 'turn', message: 'hỏi' }
      await apiStream('/api/v1/chat', body)
      const init = fetchMock.mock.calls[0]?.[1] as RequestInit
      expect(init).toMatchObject({ credentials: 'include', method: 'POST' })
      expect(JSON.parse(init.body as string)).not.toHaveProperty('history')
   })
})
