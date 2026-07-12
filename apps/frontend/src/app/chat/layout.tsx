import { Suspense } from 'react'

export const metadata = {
  title: 'ChatLegal | LegalGraph AI',
  description: 'Tra cứu và phân tích văn bản pháp luật với trợ lý ảo.',
}

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense>
      {children}
    </Suspense>
  )
}
