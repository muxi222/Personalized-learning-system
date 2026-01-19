import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi } from '../lib/api'
import { SUBJECT_NAMES_CN } from '../config/moduleRouting'
import {
  Clock,
  ArrowRight,
  Trophy,
  BookOpen,
  Sparkles
} from 'lucide-react'
import clsx from 'clsx'

export default function ReviewPage() {
  const [subject, setSubject] = useState('')
  const [chapter, setChapter] = useState('')

  const chaptersQuery = useQuery({
    queryKey: ['question-chapters', { subject }],
    enabled: !!subject,
    queryFn: () => questionApi.getChapters({ subject }),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['review-due', { limit: 20, subject, chapter }],
    queryFn: () => questionApi.getDueForReview({
      limit: 20,
      subject: subject || undefined,
      chapter: chapter || undefined,
    }),
  })

  const questions = data?.data || []

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-3xl font-bold text-white mb-2">
              复习计划
            </h1>
            <p className="text-slate-400">
              基于艾宾浩斯遗忘曲线，推荐最佳复习时间
            </p>
          </div>
          <Link to="/companion" className="btn-primary inline-flex items-center gap-2">
            <Sparkles className="w-4 h-4" />
            让小书童带我复习
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4 mb-6">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">学科</span>
            <select
              value={subject}
              onChange={(e) => {
                setSubject(e.target.value)
                setChapter('')
              }}
              className="input w-auto"
            >
              <option value="">全部学科</option>
              {Object.entries(SUBJECT_NAMES_CN).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">题目类型</span>
            <select
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
              className="input w-auto"
              disabled={!subject || chaptersQuery.isLoading}
            >
              <option value="">{subject ? '全部题目类型' : '请先选择学科'}</option>
              {(chaptersQuery.data?.data?.items || [])
                .filter(it => it.subject === subject)
                .flatMap(it => it.chapters || [])
                .map((c) => (
                  <option key={c.chapter} value={c.chapter}>
                    {c.chapter} ({c.count})
                  </option>
                ))}
            </select>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="card p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-slate-400 text-sm">待复习</p>
              <p className="text-2xl font-bold text-white mt-1">
                {questions.length}
              </p>
            </div>
            <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
              <Clock className="w-6 h-6 text-amber-400" />
            </div>
          </div>
        </div>

        <div className="card p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-slate-400 text-sm">今日已复习</p>
              <p className="text-2xl font-bold text-white mt-1">0</p>
            </div>
            <div className="w-12 h-12 rounded-xl bg-emerald-500/20 flex items-center justify-center">
              <BookOpen className="w-6 h-6 text-emerald-400" />
            </div>
          </div>
        </div>

        <div className="card p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-slate-400 text-sm">连续复习</p>
              <p className="text-2xl font-bold text-white mt-1">0 天</p>
            </div>
            <div className="w-12 h-12 rounded-xl bg-accent-500/20 flex items-center justify-center">
              <Trophy className="w-6 h-6 text-accent-400" />
            </div>
          </div>
        </div>
      </div>

      {/* Review list */}
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
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white text-lg">需要复习的题目</h2>
            {questions.length > 0 && (
              <Link
                to={`/questions/${questions[0].id}${questions[0]?.subject ? `?subject=${encodeURIComponent(questions[0].subject)}` : ''}`}
                className="btn-primary flex items-center gap-2"
              >
                开始复习
                <ArrowRight className="w-4 h-4" />
              </Link>
            )}
          </div>

          {questions.map((question, index) => (
            <Link
              key={question.id}
              to={`/questions/${question.id}${question.subject ? `?subject=${encodeURIComponent(question.subject)}` : ''}`}
              className="card p-6 block hover:border-primary-500/50 transition-all animate-slide-up"
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-medium text-white mb-2 line-clamp-1">
                    {question.title || (question.content ? question.content.slice(0, 80) : '题目内容')}
                  </h3>
                  <p className="text-slate-400 text-sm line-clamp-2 mb-3">
                    {question.content}
                  </p>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="badge-primary">
                      {question.subject}
                    </span>
                    <span className={clsx(
                      'badge',
                      (Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0) < 0.3 && 'bg-red-500/20 text-red-300 border border-red-500/30',
                      (Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0) >= 0.3 && (Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0) < 0.7 && 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
                      (Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0) >= 0.7 && 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
                    )}>
                      掌握度 {((Number.isFinite(Number(question.mastery_level)) ? Number(question.mastery_level) : 0) * 100).toFixed(0)}%
                    </span>
                    <span className="text-slate-500 text-xs">
                      已复习 {question.review_count || 0} 次
                    </span>
                    {question.last_reviewed_at && (
                      <span className="text-slate-500 text-xs">
                        上次复习: {new Date(question.last_reviewed_at).toLocaleDateString('zh-CN')}
                      </span>
                    )}
                  </div>
                </div>
                <ArrowRight className="w-5 h-5 text-slate-500 flex-shrink-0 mt-1" />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-12 text-center">
          <Trophy className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">太棒了！</h3>
          <p className="text-slate-400 mb-4">
            目前没有需要复习的题目，继续保持！
          </p>
          <Link to="/submit" className="btn-primary inline-flex items-center gap-2">
            录入新错题
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      )}
    </div>
  )
}
