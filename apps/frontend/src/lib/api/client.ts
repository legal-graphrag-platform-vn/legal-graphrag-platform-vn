// Base API client — xử lý fetch, error và base URL
export function getBaseUrl(): string {
   if (typeof window === 'undefined') {
      // Server-side execution (Node.js/SSR inside Docker)
      return process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://backend:8000'
   }
   // Client-side execution (inside Browser)
   return process.env.NEXT_PUBLIC_API_URL || ''
}

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

function resolveUrl(path: string): string {
   const base = getBaseUrl()
   if (!base) return path
   const cleanBase = base.endsWith('/') ? base.slice(0, -1) : base
   const cleanPath = path.startsWith('/') ? path : `/${path}`
   return `${cleanBase}${cleanPath}`
}

export async function apiGet<T>(
   path: string,
   params?: Record<string, string | undefined>,
): Promise<T> {
   const rawUrl = resolveUrl(path)
   const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'
   const url = rawUrl.startsWith('http') ? new URL(rawUrl) : new URL(rawUrl, origin)

   if (params) {
      Object.entries(params).forEach(([k, v]) => {
         if (v !== undefined && v !== null && v !== '') {
            url.searchParams.set(k, v)
         }
      })
   }
   const res = await fetch(url.toString(), { credentials: 'include' })
   if (!res.ok) {
      throw await apiError(res, path)
   }
   return res.json() as Promise<T>
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
   const url = resolveUrl(path)
   const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
   })
   if (!res.ok) {
      throw await apiError(res, path)
   }
   return res.json() as Promise<T>
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
   const url = resolveUrl(path)
   const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
   })
   if (!res.ok) {
      throw await apiError(res, path)
   }
   return res.json() as Promise<T>
}

export async function apiDelete<T = void>(path: string): Promise<T> {
   const url = resolveUrl(path)
   const res = await fetch(url, {
      method: 'DELETE',
      credentials: 'include',
   })
   if (!res.ok) {
      throw await apiError(res, path)
   }
   try {
      return (await res.json()) as T
   } catch {
      return undefined as T
   }
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
   const url = resolveUrl(path)
   return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
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
