import type { Metadata } from 'next'
import Link from 'next/link'
import {
  Scale,
  Search,
  GitBranch,
  Zap,
  ShieldCheck,
  Clock,
  ChevronRight,
  ArrowRight,
  BookOpen,
  MessageSquare,
  BarChart3,
  Check,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export const metadata: Metadata = {
  title: 'LegalGraph AI — Tra cứu pháp luật Việt Nam bằng AI',
  description:
    'Nền tảng AI tra cứu và phân tích văn bản pháp luật Việt Nam. Tìm kiếm chính xác, phân tích quan hệ văn bản, cập nhật hiệu lực theo thời gian thực.',
}

const FEATURES = [
  {
    icon: Search,
    title: 'Tìm kiếm ngữ nghĩa',
    desc: 'Đặt câu hỏi bằng ngôn ngữ tự nhiên. Hệ thống hiểu ý định và trả về đúng điều khoản liên quan.',
    color: 'text-emerald-500',
    bg: 'bg-emerald-500/10',
  },
  {
    icon: GitBranch,
    title: 'Đồ thị quan hệ văn bản',
    desc: 'Trực quan hoá quan hệ giữa các văn bản: thay thế, sửa đổi, hướng dẫn, tham chiếu chéo.',
    color: 'text-blue-500',
    bg: 'bg-blue-500/10',
  },
  {
    icon: Clock,
    title: 'Lọc theo thời điểm hiệu lực',
    desc: 'Tra cứu văn bản đang có hiệu lực tại bất kỳ thời điểm nào trong quá khứ hoặc hiện tại.',
    color: 'text-amber-500',
    bg: 'bg-amber-500/10',
  },
  {
    icon: ShieldCheck,
    title: 'Trích dẫn có kiểm chứng',
    desc: 'Mỗi câu trả lời đều đi kèm điều khoản gốc và điểm tin cậy. Không ảo giác, không suy diễn.',
    color: 'text-violet-500',
    bg: 'bg-violet-500/10',
  },
  {
    icon: BarChart3,
    title: 'Hybrid Retrieval',
    desc: 'Kết hợp Vector Search + Graph Expansion + BM25 Fulltext + Cross-encoder Reranking.',
    color: 'text-pink-500',
    bg: 'bg-pink-500/10',
  },
  {
    icon: Zap,
    title: 'Phản hồi tức thì',
    desc: 'Streaming SSE — chữ xuất hiện ngay khi AI đang phân tích, không cần chờ đợi.',
    color: 'text-orange-500',
    bg: 'bg-orange-500/10',
  },
]

const STATS = [
  { value: '10.000+', label: 'Văn bản pháp luật' },
  { value: '500ms', label: 'Thời gian phản hồi trung bình' },
  { value: '95%', label: 'Độ chính xác trích dẫn' },
  { value: '2020–nay', label: 'Phủ sóng hiệu lực' },
]

const PLANS = [
  {
    name: 'Miễn phí',
    price: '0đ',
    per: 'mãi mãi',
    features: ['20 câu hỏi/ngày', 'Tra cứu văn bản cơ bản', 'Đồ thị quan hệ (depth 1)'],
    cta: 'Bắt đầu ngay',
    href: '/chat',
    highlight: false,
  },
  {
    name: 'Chuyên nghiệp',
    price: '499.000đ',
    per: '/tháng',
    features: [
      'Không giới hạn câu hỏi',
      'Lọc theo thời điểm hiệu lực',
      'Đồ thị quan hệ (depth 2)',
      'Export PDF trích dẫn',
      'API access',
    ],
    cta: 'Dùng thử 14 ngày',
    href: '/chat',
    highlight: true,
  },
  {
    name: 'Doanh nghiệp',
    price: 'Liên hệ',
    per: '',
    features: [
      'Tất cả tính năng Pro',
      'Deploy on-premise',
      'Fine-tune theo ngành',
      'SLA 99.9%',
      'Hỗ trợ ưu tiên 24/7',
    ],
    cta: 'Liên hệ tư vấn',
    href: 'mailto:contact@legalgraph.ai',
    highlight: false,
  },
]

const USECASES = [
  { icon: Scale, title: 'Luật sư & Văn phòng luật', desc: 'Tra cứu án lệ, điều khoản liên quan, đối chiếu văn bản cũ-mới.' },
  { icon: BookOpen, title: 'Doanh nghiệp', desc: 'Tuân thủ pháp lý, kiểm tra hợp đồng, theo dõi thay đổi quy định.' },
  { icon: MessageSquare, title: 'Nghiên cứu & Học thuật', desc: 'Phân tích lịch sử lập pháp, so sánh văn bản đa thời kỳ.' },
]

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      {/* ── Navbar ── */}
      <header className="fixed top-0 inset-x-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center">
              <Scale className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-base tracking-tight">LegalGraph AI</span>
            <Badge variant="secondary" className="text-[10px] ml-1">Beta</Badge>
          </div>

          <nav className="hidden md:flex items-center gap-6 text-sm text-muted-foreground">
            <a href="#features" className="hover:text-foreground transition-colors">Tính năng</a>
            <a href="#usecases" className="hover:text-foreground transition-colors">Ứng dụng</a>
            <a href="#pricing" className="hover:text-foreground transition-colors">Bảng giá</a>
          </nav>

          <div className="flex items-center gap-2">
            <Link href="/explorer" className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}>
              Tra cứu
            </Link>
            <Link href="/chat" className={cn(buttonVariants({ size: 'sm' }), 'bg-emerald-600 hover:bg-emerald-700 text-white')}>
              Thử ngay <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative pt-32 pb-24 px-6 overflow-hidden">
        {/* Background glow */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-32 left-1/2 -translate-x-1/2 w-[800px] h-[800px] bg-emerald-500/8 rounded-full blur-3xl" />
          <div className="absolute top-20 right-0 w-[400px] h-[400px] bg-blue-500/6 rounded-full blur-3xl" />
        </div>

        <div className="relative max-w-4xl mx-auto text-center">
          <Badge variant="outline" className="mb-6 text-xs px-3 py-1 border-emerald-500/30 text-emerald-600 dark:text-emerald-400 bg-emerald-500/5">
            ✦ Được xây dựng trên Knowledge Graph + RAG
          </Badge>

          <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold tracking-tight mb-6 leading-[1.1]">
            Tra cứu pháp luật{' '}
            <span className="bg-gradient-to-r from-emerald-500 to-teal-400 bg-clip-text text-transparent">
              chính xác
            </span>
            {' '}bằng AI
          </h1>

          <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto mb-10 leading-relaxed">
            Đặt câu hỏi pháp lý bằng tiếng Việt. Nhận câu trả lời với trích dẫn điều khoản có kiểm chứng,
            đồ thị quan hệ văn bản, và lọc hiệu lực theo thời gian.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/chat" className={cn(buttonVariants({ size: 'lg' }), 'bg-emerald-600 hover:bg-emerald-700 text-white h-12 px-8 text-base')}>
              Bắt đầu miễn phí <ArrowRight className="w-4 h-4 ml-2" />
            </Link>
            <Link href="/explorer" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-12 px-8 text-base')}>
              <BookOpen className="w-4 h-4 mr-2" />
              Tra cứu văn bản
            </Link>
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            Không cần đăng ký · 20 câu hỏi miễn phí mỗi ngày
          </p>
        </div>

        {/* Hero mockup */}
        <div className="relative max-w-4xl mx-auto mt-16">
          <div className="rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">
            {/* Fake browser bar */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-muted/50">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-red-400/60" />
                <div className="w-3 h-3 rounded-full bg-amber-400/60" />
                <div className="w-3 h-3 rounded-full bg-emerald-400/60" />
              </div>
              <div className="flex-1 mx-4 bg-background/60 rounded-md px-3 py-1 text-xs text-muted-foreground border border-border/50">
                legalgraph.ai/chat
              </div>
            </div>
            {/* Mock chat */}
            <div className="p-6 space-y-4 bg-background">
              <div className="flex justify-end">
                <div className="bg-muted rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm max-w-xs">
                  Điều kiện thành lập công ty cổ phần theo Luật Doanh nghiệp mới nhất?
                </div>
              </div>
              <div className="flex gap-3 max-w-2xl">
                <div className="w-7 h-7 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
                  <Scale className="w-3.5 h-3.5 text-emerald-600" />
                </div>
                <div className="space-y-2">
                  <p className="text-sm leading-relaxed">
                    Theo <span className="font-semibold text-emerald-600">Điều 111, Luật Doanh nghiệp 59/2020/QH14</span>,
                    công ty cổ phần được thành lập khi đáp ứng các điều kiện sau:
                  </p>
                  <ul className="text-sm space-y-1 text-muted-foreground">
                    <li className="flex gap-2"><span className="text-emerald-500 mt-0.5">▸</span> Có tối thiểu <strong className="text-foreground">3 cổ đông sáng lập</strong></li>
                    <li className="flex gap-2"><span className="text-emerald-500 mt-0.5">▸</span> Vốn điều lệ được chia thành các <strong className="text-foreground">cổ phần bằng nhau</strong></li>
                    <li className="flex gap-2"><span className="text-emerald-500 mt-0.5">▸</span> Đăng ký kinh doanh tại <strong className="text-foreground">Cơ quan đăng ký kinh doanh</strong></li>
                  </ul>
                  {/* Source chips */}
                  <div className="flex gap-1.5 pt-1 flex-wrap">
                    {['Điều 111 LDN 2020', 'NĐ 01/2021/NĐ-CP', 'Điều 22'].map((s) => (
                      <span key={s} className="text-[10px] px-2 py-0.5 rounded-full border border-emerald-500/30 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats ── */}
      <section className="border-y border-border bg-muted/30 py-12">
        <div className="max-w-4xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <div key={s.label}>
              <p className="text-3xl font-bold text-foreground">{s.value}</p>
              <p className="text-sm text-muted-foreground mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <Badge variant="outline" className="mb-4 text-xs">Tính năng</Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Mọi thứ bạn cần cho tra cứu pháp lý
            </h2>
            <p className="text-muted-foreground max-w-xl mx-auto">
              Được xây dựng trên nền tảng Knowledge Graph và Retrieval-Augmented Generation —
              không phải chatbot thông thường.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="group p-6 rounded-2xl border border-border bg-card hover:border-emerald-500/30 hover:bg-muted/50 transition-all duration-300"
              >
                <div className={`w-10 h-10 rounded-xl ${f.bg} flex items-center justify-center mb-4`}>
                  <f.icon className={`w-5 h-5 ${f.color}`} />
                </div>
                <h3 className="font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Use cases ── */}
      <section id="usecases" className="py-24 px-6 bg-muted/20">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <Badge variant="outline" className="mb-4 text-xs">Ứng dụng</Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Phù hợp với mọi đối tượng pháp lý
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-6">
            {USECASES.map((u) => (
              <div key={u.title} className="p-8 rounded-2xl border border-border bg-card text-center hover:shadow-lg transition-shadow">
                <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 flex items-center justify-center mx-auto mb-5">
                  <u.icon className="w-7 h-7 text-emerald-500" />
                </div>
                <h3 className="font-semibold text-base mb-3">{u.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{u.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <Badge variant="outline" className="mb-4 text-xs">Bảng giá</Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Minh bạch, không ẩn phí</h2>
            <p className="text-muted-foreground">Bắt đầu miễn phí, nâng cấp khi cần.</p>
          </div>

          <div className="grid md:grid-cols-3 gap-6 items-start">
            {PLANS.map((plan) => (
              <div
                key={plan.name}
                className={`relative p-8 rounded-2xl border transition-all ${
                  plan.highlight
                    ? 'border-emerald-500 bg-emerald-500/5 shadow-xl shadow-emerald-500/10'
                    : 'border-border bg-card'
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge className="bg-emerald-500 text-white hover:bg-emerald-500 text-xs px-3">
                      Phổ biến nhất
                    </Badge>
                  </div>
                )}

                <p className="font-semibold text-sm text-muted-foreground mb-1">{plan.name}</p>
                <div className="flex items-baseline gap-1 mb-1">
                  <span className="text-3xl font-bold">{plan.price}</span>
                  {plan.per && <span className="text-sm text-muted-foreground">{plan.per}</span>}
                </div>

                <div className="my-6 space-y-3">
                  {plan.features.map((f) => (
                    <div key={f} className="flex items-center gap-2.5 text-sm">
                      <Check className="w-4 h-4 text-emerald-500 shrink-0" />
                      <span>{f}</span>
                    </div>
                  ))}
                </div>

                <Link
                  href={plan.href}
                  className={cn(
                    buttonVariants({ variant: plan.highlight ? 'default' : 'outline' }),
                    'w-full',
                    plan.highlight ? 'bg-emerald-600 hover:bg-emerald-700 text-white' : '',
                  )}
                >
                  {plan.cta} <ChevronRight className="w-4 h-4 ml-1" />
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="py-24 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <div className="relative rounded-3xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/8 to-teal-500/5 p-12 overflow-hidden">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-20 -right-20 w-64 h-64 bg-emerald-500/10 rounded-full blur-3xl" />
              <div className="absolute -bottom-20 -left-20 w-64 h-64 bg-teal-500/10 rounded-full blur-3xl" />
            </div>
            <div className="relative">
              <h2 className="text-3xl md:text-4xl font-bold mb-4">
                Sẵn sàng tra cứu thông minh hơn?
              </h2>
              <p className="text-muted-foreground mb-8 text-lg">
                Bắt đầu ngay hôm nay, miễn phí. Không cần thẻ tín dụng.
              </p>
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <Link href="/chat" className={cn(buttonVariants({ size: 'lg' }), 'bg-emerald-600 hover:bg-emerald-700 text-white h-12 px-8')}>
                  Bắt đầu Chat với AI <ArrowRight className="w-4 h-4 ml-2" />
                </Link>
                <Link href="/explorer" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-12 px-8')}>
                  <BookOpen className="w-4 h-4 mr-2" />
                  Tra cứu văn bản
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-border py-10 px-6">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-emerald-500 flex items-center justify-center">
              <Scale className="w-3 h-3 text-white" />
            </div>
            <span className="font-semibold text-foreground">LegalGraph AI</span>
            <span>— Nền tảng AI pháp lý Việt Nam</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/chat" className="hover:text-foreground transition-colors">Chat</Link>
            <Link href="/explorer" className="hover:text-foreground transition-colors">Tra cứu</Link>
            <span>© 2025 LegalGraph AI</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
