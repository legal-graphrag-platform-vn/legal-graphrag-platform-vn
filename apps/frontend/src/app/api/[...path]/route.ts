import { NextRequest, NextResponse } from 'next/server'

// URL trỏ tới Backend FastAPI:
// - Khi chạy Local Dev: trỏ tới http://127.0.0.1:8000 (từ .env.local hoặc mặc định)
// - Khi chạy Production Docker: trỏ tới http://backend:8000 (từ INTERNAL_API_URL trong .env.frontend)
const BACKEND_URL =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://127.0.0.1:8000'

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params
  const cleanBase = BACKEND_URL.endsWith('/')
    ? BACKEND_URL.slice(0, -1)
    : BACKEND_URL
  const targetUrl = `${cleanBase}/api/${path.join('/')}${req.nextUrl.search}`

  const headers = new Headers(req.headers)
  headers.delete('host')

  // Request body (cho POST, PUT, PATCH, DELETE)
  let body: BodyInit | undefined = undefined
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    body = await req.arrayBuffer()
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
      redirect: 'manual',
    })

    const responseHeaders = new Headers(backendRes.headers)
    // Giữ nguyên cookie session trả về từ backend
    const setCookie = backendRes.headers.get('set-cookie')
    if (setCookie) {
      responseHeaders.set('set-cookie', setCookie)
    }

    return new NextResponse(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: responseHeaders,
    })
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : 'Unknown proxy error'
    return NextResponse.json(
      {
        detail: `Lỗi kết nối tới Backend (${targetUrl}): ${errorMsg}`,
        code: 'BACKEND_CONNECTION_ERROR',
      },
      { status: 502 }
    )
  }
}

export const GET = proxyRequest
export const POST = proxyRequest
export const PUT = proxyRequest
export const PATCH = proxyRequest
export const DELETE = proxyRequest
export const HEAD = proxyRequest
export const OPTIONS = proxyRequest
