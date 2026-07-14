import type { Metadata } from 'next'
import { ThemeProvider } from '@/components/layout/ThemeProvider'
import './globals.css'

export const metadata: Metadata = {
   title: 'LegalGraph AI — Pilot tra cứu pháp luật',
   description:
      'Giao diện nghiên cứu GraphRAG cho Luật Doanh nghiệp 2020 với trích dẫn Điều, Khoản.',
}

export default function RootLayout({
   children,
}: Readonly<{
   children: React.ReactNode
}>) {
   return (
      <html
         lang="vi"
         className="h-full scroll-smooth antialiased"
         data-scroll-behavior="smooth"
         suppressHydrationWarning
      >
         <body className="flex min-h-full flex-col">
            <ThemeProvider
               attribute="class"
               defaultTheme="system"
               enableSystem
               disableTransitionOnChange
            >
               {children}
            </ThemeProvider>
         </body>
      </html>
   )
}
