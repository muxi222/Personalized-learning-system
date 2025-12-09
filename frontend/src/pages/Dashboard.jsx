import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi, feedbackApi } from '../lib/api'
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
  const { data: questionsData } = useQuery({
    queryKey: ['questions', { page: 1, page_size: 5 }],
    queryFn: () => questionApi.list({ page: 1, page_size: 5 }),
  })

  const { data: reviewData } = useQuery({
    queryKey: ['review-due', 5],
    queryFn: () => questionApi.getDueForReview({ limit: 5 }),
  })

  const { data: statsData } = useQuery({
    queryKey: ['feedback-stats'],
    queryFn: feedbackApi.getStats,
  })

  const recentQuestions = questionsData?.data?.items || []
  const reviewQuestions = reviewData?.data || []
  const stats = statsData?.data || {}

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="font-display text-3xl font-bold text-white mb-2">
          学习仪表盘
        </h1>
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
            value: stats.average_rating?.toFixed(1) || '-',
            color: 'emerald',
          },
          { 
            icon: Target, 
            label: '反馈率', 
            value: `${((stats.feedback_rate || 0) * 100).toFixed(0)}%`,
            color: 'accent',
          },
        ].map(({ icon: Icon, label, value, color }, index) => (
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
              <div className={`w-12 h-12 rounded-xl bg-${color}-500/20 flex items-center justify-center`}>
                <Icon className={`w-6 h-6 text-${color}-400`} />
              </div>
            </div>
          </div>
        ))}
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
                  to={`/questions/${question.id}`}
                  className="block p-4 bg-slate-800/50 rounded-xl hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">
                        {question.title || question.content.slice(0, 50)}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className="badge-primary text-xs">
                          {question.subject}
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
              {reviewQuestions.map((question) => (
                <Link
                  key={question.id}
                  to={`/questions/${question.id}`}
                  className="block p-4 bg-slate-800/50 rounded-xl hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">
                        {question.title || question.content.slice(0, 50)}
                      </p>
                      <div className="flex items-center gap-3 mt-2">
                        <span className="badge-warning text-xs">
                          掌握度 {(question.mastery_level * 100).toFixed(0)}%
                        </span>
                        <span className="text-slate-500 text-xs">
                          复习 {question.review_count} 次
                        </span>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                  </div>
                </Link>
              ))}
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

