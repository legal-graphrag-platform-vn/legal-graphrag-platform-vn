// Base API client — xử lý fetch, error và base URL
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
   constructor(
      public status: number,
      message: string,
      public code?: string,
   ) {
      super(message)
      this.name = 'ApiError'
   }
}

export async function apiGet<T>(
   path: string,
   params?: Record<string, string | undefined>,
): Promise<T> {
   const url = new URL(`${BASE_URL}${path}`)
   if (params) {
      Object.entries(params).forEach(([k, v]) => {
         if (v !== undefined && v !== null && v !== '') {
            url.searchParams.set(k, v)
         }
      })
   }
   const res = await fetch(url.toString())
   if (!res.ok) {
      throw await apiError(res, path)
   }
   return res.json() as Promise<T>
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
   const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
   })
   if (!res.ok) {
      throw await apiError(res, path)
   }
   return res.json() as Promise<T>
}

/**
 * Mở SSE stream cho chat endpoint.
 * Dùng fetch() + ReadableStream thay vì EventSource (chỉ hỗ trợ GET).
 */
export async function apiStream(
   path: string,
   body: unknown,
   signal?: AbortSignal,
): Promise<Response> {
   return fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
   })
}

async function apiError(response: Response, path: string): Promise<ApiError> {
   try {
      const payload: unknown = await response.json()
      if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
         const body = payload as Record<string, unknown>
         const message = typeof body.message === 'string' ? body.message : undefined
         const code = typeof body.code === 'string' ? body.code : undefined
         if (message) return new ApiError(response.status, message, code)
      }
   } catch {
      // Non-JSON responses use the stable transport-level fallback below.
   }
   return new ApiError(response.status, `API error ${response.status}: ${path}`)
}
