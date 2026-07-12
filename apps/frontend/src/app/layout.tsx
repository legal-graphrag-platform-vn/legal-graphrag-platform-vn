import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { ThemeProvider } from '@/components/layout/ThemeProvider'
import './globals.css'

const geistSans = Geist({
   variable: '--font-geist-sans',
   subsets: ['latin'],
})

const geistMono = Geist_Mono({
   variable: '--font-geist-mono',
   subsets: ['latin'],
})

export const metadata: Metadata = {
   title: 'LegalGraph AI — Tra cứu pháp luật Việt Nam bằng AI',
   description: 'Nền tảng AI tra cứu và phân tích văn bản pháp luật Việt Nam. Tìm kiếm chính xác, phân tích quan hệ văn bản, cập nhật hiệu lực theo thời gian thực.',
}

export default function RootLayout({
   children,
}: Readonly<{
   children: React.ReactNode
}>) {
   return (
      <html lang="vi" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased scroll-smooth`} suppressHydrationWarning>
         <body className="min-h-full flex flex-col">
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
