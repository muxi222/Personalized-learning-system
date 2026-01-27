import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { BookOpen, Eye, EyeOff, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

export default function Register() {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
    full_name: '',
    grade: '',
  })
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({})
  const { register } = useAuthStore()
  const navigate = useNavigate()

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
    // 清除该字段的错误
    if (fieldErrors[e.target.name]) {
      setFieldErrors({ ...fieldErrors, [e.target.name]: undefined })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (formData.password !== formData.confirmPassword) {
      toast.error('两次输入的密码不一致')
      return
    }

    setLoading(true)

    // 清除之前的错误
    setFieldErrors({})

    const result = await register({
      username: formData.username,
      email: formData.email,
      password: formData.password,
      full_name: formData.full_name || null,
      grade: formData.grade || null,
    })

    setLoading(false)

    if (result.success) {
      toast.success('注册成功！')
      navigate('/')
    } else {
      // 解析错误信息，提取字段错误
      const errorMessage = result.error || '注册失败'
      toast.error(errorMessage)

      // 尝试解析字段错误
      if (result.errorDetails && Array.isArray(result.errorDetails)) {
        const errors = {}
        result.errorDetails.forEach(err => {
          const field = err.field.replace('body -> ', '')
          let message = err.message

          // 友好的错误消息翻译
          if (message.includes('at least 3 characters')) {
            message = '至少需要3个字符'
          } else if (message.includes('at least 6 characters')) {
            message = '至少需要6个字符'
          } else if (message.includes('Invalid email') || message.includes('value is not a valid email')) {
            message = '邮箱格式不正确'
          }

          errors[field] = message
        })
        setFieldErrors(errors)
      }
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 py-12">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-primary-500 to-accent-500 rounded-2xl mb-4">
            <BookOpen className="w-8 h-8 text-white" />
          </div>
          <h1 className="font-display text-3xl font-bold text-white mb-2">
            灵动书童
          </h1>
          <p className="text-slate-400">开启智能学习之旅</p>
        </div>

        {/* Register form */}
        <div className="card p-8">
          <h2 className="text-xl font-semibold text-white mb-6">创建账号</h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  用户名 *
                </label>
                <input
                  type="text"
                  name="username"
                  value={formData.username}
                  onChange={handleChange}
                  className={`input ${fieldErrors.username ? 'border-red-500' : ''}`}
                  placeholder="用户名（至少3个字符）"
                  required
                  minLength={3}
                />
                {fieldErrors.username && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.username}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  姓名
                </label>
                <input
                  type="text"
                  name="full_name"
                  value={formData.full_name}
                  onChange={handleChange}
                  className="input"
                  placeholder="真实姓名"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                邮箱 *
              </label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                className={`input ${fieldErrors.email ? 'border-red-500' : ''}`}
                placeholder="your@email.com"
                required
              />
              {fieldErrors.email && (
                <p className="mt-1 text-sm text-red-400">{fieldErrors.email}</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                年级
              </label>
              <select
                name="grade"
                value={formData.grade}
                onChange={handleChange}
                className="input"
              >
                <option value="">选择年级</option>
                <option value="初一">初一</option>
                <option value="初二">初二</option>
                <option value="初三">初三</option>
                <option value="高一">高一</option>
                <option value="高二">高二</option>
                <option value="高三">高三</option>
                <option value="大学">大学</option>
                <option value="其他">其他</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                密码 *
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  value={formData.password}
                  onChange={handleChange}
                  className={`input pr-12 ${fieldErrors.password ? 'border-red-500' : ''}`}
                  placeholder="至少6位密码"
                  required
                  minLength={6}
                />
                {fieldErrors.password && (
                  <p className="mt-1 text-sm text-red-400">{fieldErrors.password}</p>
                )}
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                确认密码 *
              </label>
              <input
                type="password"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleChange}
                className="input"
                placeholder="再次输入密码"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  注册中...
                </>
              ) : (
                '注册'
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-slate-400">
            已有账号？{' '}
            <Link to="/login" className="text-primary-400 hover:text-primary-300 font-medium">
              立即登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
