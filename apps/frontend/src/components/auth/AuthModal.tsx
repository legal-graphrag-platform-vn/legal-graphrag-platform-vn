import { useState } from 'react'
import { X, LogIn, UserPlus, LogOut, User as UserIcon, Check, Eye, EyeOff } from 'lucide-react'

interface UserProfile {
  user_id: string
  username: string
  full_name?: string | null
}

interface AuthResponse {
  user_id?: string
  username?: string
  full_name?: string | null
  detail?: string | { msg?: string; message?: string }[]
  message?: string
}

interface AuthModalProps {
  isOpen: boolean
  onClose: () => void
  user: UserProfile | null
  onLoginSuccess: (user: UserProfile) => void
  onLogout: () => void
}

export function AuthModal({
  isOpen,
  onClose,
  user,
  onLoginSuccess,
  onLogout,
}: AuthModalProps) {
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)
    setLoading(true)

    const endpoint = isRegister ? '/api/v1/auth/register' : '/api/v1/auth/login'
    const payload = isRegister
      ? { username: username.trim(), password, full_name: fullName.trim() || undefined }
      : { username: username.trim(), password }

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      })

      let data: AuthResponse = {}
      try {
        data = await res.json()
      } catch {
        data = {}
      }

      if (!res.ok) {
        let errorMessage = 'Thao tác không thành công. Vui lòng thử lại.'
        if (typeof data?.detail === 'string') {
          errorMessage = data.detail
        } else if (Array.isArray(data?.detail) && data.detail.length > 0) {
          errorMessage = data.detail
            .map((item: { msg?: string; message?: string }) => item.msg || item.message || '')
            .filter(Boolean)
            .join('; ')
        } else if (typeof data?.message === 'string') {
          errorMessage = data.message
        }
        throw new Error(errorMessage || 'Thao tác không thành công.')
      }

      setSuccessMsg(
        isRegister ? 'Đăng ký tài khoản thành công!' : 'Đăng nhập thành công!'
      )
      onLoginSuccess({
        user_id: data.user_id || '',
        username: data.username || '',
        full_name: data.full_name,
      })

      setTimeout(() => {
        onClose()
        setUsername('')
        setPassword('')
        setShowPassword(false)
        setFullName('')
        setSuccessMsg(null)
      }, 800)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Lỗi kết nối máy chủ.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleLogoutClick = async () => {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include' })
    } catch {}
    onLogout()
    onClose()
  }

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200 cursor-pointer"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-md bg-card rounded-2xl shadow-2xl border border-border flex flex-col animate-in fade-in zoom-in-95 duration-200 cursor-default overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border bg-zinc-50/50 dark:bg-zinc-900/50">
          <div className="flex items-center gap-2">
            <UserIcon className="w-5 h-5 text-indigo-500" />
            <h3 className="font-semibold text-base text-foreground">
              {user ? 'Thông tin tài khoản' : isRegister ? 'Đăng ký tài khoản' : 'Đăng nhập'}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-200/50 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {user ? (
            <div className="space-y-4 text-center">
              <div className="w-16 h-16 bg-indigo-100 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400 rounded-full flex items-center justify-center text-xl font-bold mx-auto border border-indigo-200 dark:border-indigo-800">
                {(user.full_name || user.username).substring(0, 2).toUpperCase()}
              </div>
              <div>
                <h4 className="font-bold text-lg text-foreground">
                  {user.full_name || user.username}
                </h4>
                <p className="text-sm text-zinc-400">@{user.username}</p>
              </div>

              <div className="pt-4 border-t border-border">
                <button
                  onClick={handleLogoutClick}
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-900/40 transition-colors cursor-pointer"
                >
                  <LogOut size={16} />
                  <span>Đăng xuất</span>
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="p-3 text-xs font-medium text-rose-600 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 rounded-xl">
                  {error}
                </div>
              )}
              {successMsg && (
                <div className="p-3 text-xs font-medium text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-center gap-1.5">
                  <Check size={14} />
                  <span>{successMsg}</span>
                </div>
              )}

              {isRegister && (
                <div>
                  <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                    Tên hiển thị (Tùy chọn)
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Nguyễn Văn A"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Tên đăng nhập (Username)
                </label>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="username"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                  Mật khẩu
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3.5 py-2.5 pr-10 rounded-xl border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors p-0.5 cursor-pointer"
                    title={showPassword ? 'Ẩn mật khẩu' : 'Hiển thị mật khẩu'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-2 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 transition-colors shadow-sm cursor-pointer"
              >
                {isRegister ? <UserPlus size={16} /> : <LogIn size={16} />}
                <span>
                  {loading
                    ? 'Đang xử lý...'
                    : isRegister
                    ? 'Đăng ký tài khoản'
                    : 'Đăng nhập'}
                </span>
              </button>

              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsRegister(!isRegister)
                    setShowPassword(false)
                    setError(null)
                  }}
                  className="text-xs text-zinc-500 dark:text-zinc-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors cursor-pointer"
                >
                  {isRegister
                    ? 'Đã có tài khoản? Đăng nhập ngay'
                    : 'Chưa có tài khoản? Đăng ký ngay'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
