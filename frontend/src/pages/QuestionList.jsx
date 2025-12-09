import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi } from '../lib/api'
import { 
  Search, 
  Filter, 
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  BookOpen
} from 'lucide-react'
import { clsx } from 'clsx'

const SUBJECTS = [
  { value: '', label: '全部学科' },
  { value: 'math', label: '数学' },
  { value: 'physics', label: '物理' },
  { value: 'chemistry', label: '化学' },
  { value: 'biology', label: '生物' },
  { value: 'english', label: '英语' },
  { value: 'chinese', label: '语文' },
  { value: 'other', label: '其他' },
]

const DIFFICULTIES = [
  { value: '', label: '全部难度' },
  { value: 'easy', label: '简单' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困难' },
]

export default function QuestionList() {
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({
    subject: '',
    difficulty: '',
    search: '',
  })
  const pageSize = 10

  const { data, isLoading } = useQuery({
    queryKey: ['questions', { page, page_size: pageSize, ...filters }],
    queryFn: () => questionApi.list({ page, page_size: pageSize, ...filters }),
    keepPreviousData: true,
  })

  const questions = data?.data?.items || []
  const total = data?.data?.total || 0
  const totalPages = Math.ceil(total / pageSize)

  const handleSearch = (e) => {
    e.preventDefault()
    setPage(1)
  }

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-white mb-2">
          错题本
        </h1>
        <p className="text-slate-400">
          共 {total} 道错题
        </p>
      </div>

      {/* Filters */}
      <div className="card p-4 mb-6">
        <form onSubmit={handleSearch} className="flex flex-wrap items-center gap-4">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
            <input
              type="text"
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              className="input pl-10"
              placeholder="搜索题目内容..."
            />
          </div>

          {/* Subject filter */}
          <select
            value={filters.subject}
            onChange={(e) => {
              setFilters({ ...filters, subject: e.target.value })
              setPage(1)
            }}
            className="input w-auto"
          >
            {SUBJECTS.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          {/* Difficulty filter */}
          <select
            value={filters.difficulty}
            onChange={(e) => {
              setFilters({ ...filters, difficulty: e.target.value })
              setPage(1)
            }}
            className="input w-auto"
          >
            {DIFFICULTIES.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          <button type="submit" className="btn-secondary flex items-center gap-2">
            <Filter className="w-4 h-4" />
            筛选
          </button>
        </form>
      </div>

      {/* Questions list */}
      {isLoading ? (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="card p-6 animate-pulse">
              <div className="h-5 bg-slate-700 rounded w-3/4 mb-3" />
              <div className="h-4 bg-slate-700 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : questions.length > 0 ? (
        <div className="space-y-4">
          {questions.map((question, index) => (
            <Link
              key={question.id}
              to={`/questions/${question.id}`}
              className="card p-6 block hover:border-primary-500/50 transition-all animate-slide-up"
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-medium text-white mb-2 line-clamp-1">
                    {question.title || question.content.slice(0, 80)}
                  </h3>
                  <p className="text-slate-400 text-sm line-clamp-2 mb-3">
                    {question.content}
                  </p>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="badge-primary">
                      {SUBJECTS.find(s => s.value === question.subject)?.label || question.subject}
                    </span>
                    <span className={clsx(
                      'badge',
                      question.difficulty === 'easy' && 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
                      question.difficulty === 'medium' && 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
                      question.difficulty === 'hard' && 'bg-red-500/20 text-red-300 border border-red-500/30',
                    )}>
                      {DIFFICULTIES.find(d => d.value === question.difficulty)?.label || question.difficulty}
                    </span>
                    {question.knowledge_points?.slice(0, 2).map((kp) => (
                      <span key={kp} className="badge-accent">
                        {kp}
                      </span>
                    ))}
                    <span className="text-slate-500 text-xs ml-auto">
                      {new Date(question.created_at).toLocaleDateString('zh-CN')}
                    </span>
                  </div>
                </div>
                <ArrowRight className="w-5 h-5 text-slate-500 flex-shrink-0 mt-1" />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-12 text-center">
          <BookOpen className="w-16 h-16 text-slate-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">暂无错题</h3>
          <p className="text-slate-400 mb-4">
            去录入第一道错题吧！
          </p>
          <Link to="/submit" className="btn-primary inline-flex items-center gap-2">
            录入错题
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="btn-secondary p-2 disabled:opacity-50"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          
          {[...Array(Math.min(5, totalPages))].map((_, i) => {
            const pageNum = i + 1
            return (
              <button
                key={pageNum}
                onClick={() => setPage(pageNum)}
                className={clsx(
                  'w-10 h-10 rounded-lg font-medium transition-colors',
                  page === pageNum
                    ? 'bg-primary-500 text-white'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                )}
              >
                {pageNum}
              </button>
            )
          })}
          
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="btn-secondary p-2 disabled:opacity-50"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      )}
    </div>
  )
}

