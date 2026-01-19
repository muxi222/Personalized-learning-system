import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../stores/authStore'
import {
  Home,
  PlusCircle,
  List,
  RefreshCw,
  LogOut,
  BookOpen,
  User,
  Camera,
  Brain,
  Sparkles,
  FileCheck
} from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { to: '/', icon: Home, label: '仪表盘' },
  { to: '/exam-upload', icon: Camera, label: 'AI批改' },
  { to: '/corrections', icon: FileCheck, label: '批改历史' },
  { to: '/submit', icon: PlusCircle, label: '录入错题' },
  { to: '/questions', icon: List, label: '错题本' },
  { to: '/learning', icon: Brain, label: '学习建议' },
  { to: '/companion', icon: Sparkles, label: '小书童', highlight: false },
  { to: '/review', icon: RefreshCw, label: '复习' },
]

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const handleNavClick = (to) => {
    // 点击导航时，主动让相关页面的核心数据失效，确保进入页面会拉取最新数据
    if (to === '/questions') {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['question-chapters'] })
      return
    }
    if (to === '/review') {
      queryClient.invalidateQueries({ queryKey: ['review-due'] })
      queryClient.invalidateQueries({ queryKey: ['question-chapters'] })
      return
    }
    if (to === '/corrections') {
      queryClient.invalidateQueries({ queryKey: ['corrections'] })
      return
    }
    if (to === '/learning') {
      queryClient.invalidateQueries({ queryKey: ['learning-profile'] })
      queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      queryClient.invalidateQueries({ queryKey: ['study-plan'] })
      queryClient.invalidateQueries({ queryKey: ['learning-summary'] })
      return
    }
    if (to === '/companion') {
      queryClient.invalidateQueries({ queryKey: ['companion-conversations'] })
      queryClient.invalidateQueries({ queryKey: ['companion-conversation'] })
      return
    }
    if (to === '/') {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['review-due'] })
      queryClient.invalidateQueries({ queryKey: ['feedback-stats'] })
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900/80 backdrop-blur-xl border-r border-slate-800/50 flex flex-col">
        {/* Logo */}
        <div className="p-6 border-b border-slate-800/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-display font-bold text-lg text-white">AI学习小书童</h1>
              <p className="text-xs text-slate-500">智能错题分析</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map(({ to, icon: Icon, label, highlight }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => handleNavClick(to)}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200',
                  isActive
                    ? 'bg-gradient-to-r from-primary-500/20 to-accent-500/20 text-white border border-primary-500/30'
                    : highlight
                    ? 'text-primary-400 hover:text-white bg-primary-500/10 hover:bg-primary-500/20 border border-primary-500/20'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                )
              }
            >
              <Icon className={clsx('w-5 h-5', highlight && 'text-primary-400')} />
              <span className="font-medium">{label}</span>
              {highlight && (
                <span className="ml-auto px-2 py-0.5 bg-primary-500 text-white text-xs rounded-full">
                  新
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* User section */}
        <div className="p-4 border-t border-slate-800/50">
          <div className="flex items-center gap-3 px-4 py-3">
            <div className="w-9 h-9 bg-slate-700 rounded-full flex items-center justify-center">
              <User className="w-4 h-4 text-slate-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">
                {user?.full_name || user?.username || '用户'}
              </p>
              <p className="text-xs text-slate-500 truncate">
                {user?.grade || '学生'}
              </p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-3 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-xl transition-all duration-200"
          >
            <LogOut className="w-5 h-5" />
            <span className="font-medium">退出登录</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-8 max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
