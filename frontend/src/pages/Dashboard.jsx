import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi, feedbackApi } from '../lib/api'
import { SUBJECT_NAMES_CN } from '../config/moduleRouting'
import {
  BookOpen,
  PlusCircle,
  TrendingUp,
  Clock,
  Star,
  ArrowRight,
  Target
} from 'lucide-react'

export default function Dashboard() {
  const [subject, setSubject] = useState('')

  const { data: questionsData } = useQuery({
    queryKey: ['questions', { page: 1, page_size: 5, subject, group_by: 'none' }],
    queryFn: () => questionApi.list({
      page: 1,
      page_size: 5,
      group_by: 'none', // Dashboard 需要平铺列表，否则默认 group_by=upload 会返回分组结构导致页面崩溃
      subject: subject || undefined,
    }),
  })

  const { data: reviewData } = useQuery({
    queryKey: ['review-due', { limit: 5, subject }],
    queryFn: () => questionApi.getDueForReview({ limit: 5, subject: subject || undefined }),
  })

  const { data: statsData } = useQuery({
    queryKey: ['feedback-stats', { subject }],
    queryFn: () => feedbackApi.getStats(subject || undefined),
  })

  const recentQuestions = questionsData?.data?.items || []
  const reviewQuestions = reviewData?.data || []
  const stats = statsData?.data || {}

  const avgRatingText = useMemo(() => {
    const v = Number(stats?.average_rating)
    return Number.isFinite(v) ? v.toFixed(1) : '-'
  }, [stats?.average_rating])

  const feedbackRateText = useMemo(() => {
    const v = Number(stats?.feedback_rate)
    const pct = Number.isFinite(v) ? v * 100 : 0
    return `${pct.toFixed(0)}%`
  }, [stats?.feedback_rate])

  const statColors = {
    primary: { bg: 'bg-primary-500/20', text: 'text-primary-400' },
    amber: { bg: 'bg-amber-500/20', text: 'text-amber-400' },
    emerald: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
    accent: { bg: 'bg-accent-500/20', text: 'text-accent-400' },
  }

  const subjectLabel = subject ? (SUBJECT_NAMES_CN[subject] || subject) : '全部学科'

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-3xl font-bold text-white mb-2">
              学习仪表盘
            </h1>
            <p className="text-slate-400">
              当前：{subjectLabel}
            </p>
          </div>

          <select
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="input w-auto"
          >
            <option value="">全部学科</option>
            {Object.entries(SUBJECT_NAMES_CN).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
        </div>
        <p className="text-slate-400">
          追踪你的学习进度，发现知识薄弱点
        </p>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          {
            icon: BookOpen,
            label: '错题总数',
            value: questionsData?.data?.total || 0,
            color: 'primary',
          },
          {
            icon: Clock,
            label: '待复习',
            value: reviewQuestions.length,
            color: 'amber',
          },
          {
            icon: Star,
            label: '平均评分',
            value: avgRatingText,
            color: 'emerald',
          },
          {
            icon: Target,
            label: '反馈率',
            value: feedbackRateText,
            color: 'accent',
          },
        ].map(({ icon: Icon, label, value, color }, index) => {
          const c = statColors[color] || statColors.primary
          return (
          <div
            key={label}
            className="card p-6 animate-slide-up"
            style={{ animationDelay: `${index * 100}ms` }}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-sm">{label}</p>
                <p className="text-2xl font-bold text-white mt-1">{value}</p>
              </div>
              <div className={`w-12 h-12 rounded-xl ${c.bg} flex items-center justify-center`}>
                <Icon className={`w-6 h-6 ${c.text}`} />
              </div>
            </div>
          </div>
          )
        })}
      </div>

      {/* Quick action */}
      <div className="card p-6 bg-gradient-to-r from-primary-500/10 to-accent-500/10 border-primary-500/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
              <PlusCircle className="w-7 h-7 text-white" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-lg">录入新错题</h3>
              <p className="text-slate-400 text-sm">AI会自动分析错因并生成举一反三题目</p>
            </div>
          </div>
          <Link to="/submit" className="btn-primary flex items-center gap-2">
            开始录入
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>

      {/* Content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent questions */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white text-lg">最近错题</h2>
            <Link
              to="/questions"
              className="text-primary-400 hover:text-primary-300 text-sm flex items-center gap-1"
            >
              查看全部 <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {recentQuestions.length > 0 ? (
            <div className="space-y-3">
              {recentQuestions.map((question) => (
                <Link
                  key={question.id}
                    to={`/questions/${question.id}${question.subject ? `?subject=${encodeURIComponent(question.subject)}` : ''}`}
                  className="block p-4 bg-slate-800/50 rounded-xl hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">
                        {question.title || (question.content ? question.content.slice(0, 50) : '题目内容')}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className="badge-primary text-xs">
                          {SUBJECT_NAMES_CN[question.subject] || question.subject}
                        </span>
                        <span className="text-slate-500 text-xs">
                          {new Date(question.created_at).toLocaleDateString('zh-CN')}
                        </span>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-center py-8">
              暂无错题，去录入第一道吧！
            </p>
          )}
        </div>

        {/* Review queue */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white text-lg">待复习</h2>
            <Link
              to="/review"
              className="text-primary-400 hover:text-primary-300 text-sm flex items-center gap-1"
            >
              开始复习 <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {reviewQuestions.length > 0 ? (
            <div className="space-y-3">
              {reviewQuestions.map((question) => {
                const mastery = Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0
                return (
                <Link
                  key={question.id}
                  to={`/questions/${question.id}${question.subject ? `?subject=${encodeURIComponent(question.subject)}` : ''}`}
                  className="block p-4 bg-slate-800/50 rounded-xl hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">
                        {question.title || (question.content ? question.content.slice(0, 50) : '题目内容')}
                      </p>
                      <div className="flex items-center gap-3 mt-2">
                        <span className="badge-warning text-xs">
                          掌握度 {(mastery * 100).toFixed(0)}%
                        </span>
                        <span className="badge-primary text-xs">
                          {SUBJECT_NAMES_CN[question.subject] || question.subject}
                        </span>
                        <span className="text-slate-500 text-xs">
                          复习 {question.review_count} 次
                        </span>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                  </div>
                </Link>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-8">
              <TrendingUp className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
              <p className="text-slate-400">
                太棒了！暂无需要复习的错题
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
