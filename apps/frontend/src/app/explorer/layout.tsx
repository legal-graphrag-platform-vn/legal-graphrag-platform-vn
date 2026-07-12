import { Suspense } from 'react'

export const metadata = {
  title: 'Tra cứu văn bản pháp luật | Legal GraphRAG',
  description: 'Tra cứu, tìm kiếm và phân tích quan hệ giữa các văn bản pháp luật Việt Nam.',
}

export default function ExplorerLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense>
      {children}
    </Suspense>
  )
}
