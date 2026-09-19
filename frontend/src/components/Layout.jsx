import { useEffect, useRef, useState } from 'react'
import { Outlet, NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../stores/authStore'
import { BookOpen, ChevronDown, ChevronRight, LogOut, Search, User, ArrowUpRight, CalendarDays, Menu, X } from 'lucide-react'

const navItems = [
  { to: '/', label: '学习首页' },
  { to: '/exam-upload', label: 'AI 批改' },
  { to: '/corrections', label: '批改历史' },
  { to: '/submit', label: '录入错题' },
  { to: '/questions', label: '错题本' },
  { to: '/review', label: '复习练习' },
  { to: '/learning', label: '学习建议' },
  { to: '/companion', label: '小书童' },
]

const queryKeysByPath = {
  '/': ['questions', 'review-due', 'feedback-stats'],
  '/questions': ['questions', 'question-chapters'],
  '/review': ['review-due', 'question-chapters'],
  '/corrections': ['corrections'],
  '/learning': ['learning-profile', 'recommendations', 'study-plan', 'learning-summary'],
  '/companion': ['companion-conversations', 'companion-conversation'],
}

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const accountRef = useRef(null)
  const current = navItems.find(item => item.to === '/' ? pathname === '/' : pathname.startsWith(item.to))
  const pageTitle = current?.label || '任务详情'
  const isDetail = current && pathname !== current.to
  const fullWidth = pathname === '/companion' || isDetail || pathname.startsWith('/tasks/')
  const displayName = user?.full_name || user?.username || '同学'

  useEffect(() => {
    setMenuOpen(false)
    if (accountRef.current) accountRef.current.open = false
    window.scrollTo({ top: 0, behavior: 'instant' })
  }, [pathname])

  useEffect(() => {
    const closeAccount = (event) => {
      if (accountRef.current && !accountRef.current.contains(event.target)) accountRef.current.open = false
    }
    const closeMenus = (event) => {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        if (accountRef.current) accountRef.current.open = false
      }
    }
    document.addEventListener('pointerdown', closeAccount)
    document.addEventListener('keydown', closeMenus)
    return () => {
      document.removeEventListener('pointerdown', closeAccount)
      document.removeEventListener('keydown', closeMenus)
    }
  }, [])

  const handleNavClick = (to) => {
    for (const key of queryKeysByPath[to] || []) queryClient.invalidateQueries({ queryKey: [key] })
    setMenuOpen(false)
  }

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <header className="site-header">
        <div className="site-width header-main">
          <Link to="/" className="brand" aria-label="灵动书童首页">
            <span className="brand-mark"><BookOpen size={27} strokeWidth={1.8} /></span>
            <span><strong>灵动书童</strong><small>LEARNING ASSISTANT</small></span>
          </Link>
          <span className="workspace-label">学习中心</span>
          <form className="header-search" role="search" onSubmit={(event) => {
            event.preventDefault()
            navigate('/questions' + (search.trim() ? '?search=' + encodeURIComponent(search.trim()) : ''))
          }}>
            <input aria-label="搜索错题" placeholder="搜索我的错题" value={search} onChange={event => setSearch(event.target.value)} />
            <button type="submit" aria-label="搜索" title="搜索"><Search size={17} /></button>
          </form>
          <details className="account-menu" ref={accountRef}>
            <summary><span className="avatar avatar-small"><User size={17} /></span><span className="account-name">{displayName}</span><ChevronDown size={14} /></summary>
            <div className="account-dropdown">
              <p>{displayName}<small>{user?.grade || '学生账号'}</small></p>
              <button onClick={() => { logout(); navigate('/login') }}><LogOut size={16} />退出登录</button>
            </div>
          </details>
          <button className="mobile-nav-toggle" aria-label={menuOpen ? '收起导航' : '展开导航'} aria-expanded={menuOpen} aria-controls="primary-navigation" onClick={() => setMenuOpen(!menuOpen)}>
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
        <div className="header-navigation">
          <nav id="primary-navigation" aria-label="主导航" className={'site-width primary-navigation' + (menuOpen ? ' is-open' : '')}>
            {navItems.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === '/'} onClick={() => handleNavClick(to)} className={({ isActive }) => 'navigation-link' + (isActive ? ' is-active' : '')}>
                {label}{to === '/companion' && <span className="nav-ai">AI</span>}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <div className="site-width workspace-body">
        <nav aria-label="当前位置" className="breadcrumb">
          <Link to="/">学习中心</Link><ChevronRight size={13} />
          {isDetail ? <><Link to={current.to}>{pageTitle}</Link><ChevronRight size={13} /><span aria-current="page">详情</span></> : <span aria-current="page">{pageTitle}</span>}
        </nav>
        <div className={'workspace-grid' + (fullWidth ? ' workspace-wide' : '')}>
          <main id="main-content" className="workspace-content" tabIndex={-1}><Outlet /></main>
          {!fullWidth && (
            <aside className="study-sidebar" aria-label="个人学习信息">
              <section className="profile-panel">
                <div className="profile-cover" />
                <span className="avatar avatar-large"><User size={29} strokeWidth={1.6} /></span>
                <h2>{displayName}</h2>
                <p className="profile-grade">{user?.grade || '学生'}</p>
                <dl><div><dt>学习空间</dt><dd>个人学习</dd></div><div><dt>学科范围</dt><dd>全部学科</dd></div></dl>
                <Link className="profile-action" to="/learning">我的学习建议<ArrowUpRight size={15} /></Link>
              </section>
              <section className="sidebar-section">
                <h2><CalendarDays size={17} />学习安排</h2>
                <Link to="/review"><span className="sidebar-dot dot-blue" />错题复习<ChevronRight size={14} /></Link>
                <Link to="/corrections"><span className="sidebar-dot dot-green" />查看批改记录<ChevronRight size={14} /></Link>
                <Link to="/companion"><span className="sidebar-dot dot-amber" />与小书童对话<ChevronRight size={14} /></Link>
              </section>
              <div className="sidebar-wordmark"><BookOpen size={18} /><span>灵动书童<small>LEARNING ASSISTANT</small></span></div>
            </aside>
          )}
        </div>
      </div>
      <footer className="site-footer"><div className="site-width"><span>灵动书童 · 个人学习空间</span><Link to="/companion">小书童</Link><Link to="/questions">我的错题本</Link></div></footer>
    </div>
  )
}
