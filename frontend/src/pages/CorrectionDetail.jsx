import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileCheck,
  Image as ImageIcon,
  TrendingUp,
  Target,
  CheckCircle2,
  XCircle,
  Lightbulb,
  Award,
  BarChart3,
  Maximize2,
  Clock,
  ArrowLeftRight
} from 'lucide-react'
import clsx from 'clsx'
import ImageViewer from '../components/ImageViewer'
import ImageCompareViewer from '../components/ImageCompareViewer'

// 获取 token 的辅助函数
const getAuthToken = () => {
  const authStorage = localStorage.getItem('auth-storage')
  if (authStorage) {
    const { state } = JSON.parse(authStorage)
    return state?.token
  }
  return null
}

// API 调用
const correctionsApi = {
  get: (id) => {
    const token = getAuthToken()
    return fetch(`/api/v1/corrections/${id}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    }).then(res => res.json())
  },
}

const SUBJECT_MAP = {
  'math': { label: '数学', color: 'text-blue-600', bg: 'bg-blue-500/10' },
  'english': { label: '英语', color: 'text-green-600', bg: 'bg-green-500/10' },
  'physics': { label: '物理', color: 'text-amber-600', bg: 'bg-amber-500/10' },
  'chemistry': { label: '化学', color: 'text-purple-600', bg: 'bg-purple-500/10' },
  'chinese': { label: '语文', color: 'text-red-600', bg: 'bg-red-500/10' },
  'biology': { label: '生物', color: 'text-teal-400', bg: 'bg-teal-500/10' },
  'other': { label: '其他', color: 'text-slate-500', bg: 'bg-slate-500/10' },
}

export default function CorrectionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const [compareViewerOpen, setCompareViewerOpen] = useState(false)

  const { data: correction, isLoading, error } = useQuery({
    queryKey: ['correction', id],
    queryFn: () => correctionsApi.get(id),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <BarChart3 className="w-12 h-12 text-primary-600 animate-pulse mx-auto mb-4" />
          <p className="text-slate-500">加载批改详情中...</p>
        </div>
      </div>
    )
  }

  if (error || !correction) {
    return (
      <div className="card p-12 text-center">
        <FileCheck className="w-16 h-16 text-slate-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-slate-800 mb-2">批改记录不存在</h3>
        <button onClick={() => navigate('/corrections')} className="btn-primary mt-4">
          返回批改历史
        </button>
      </div>
    )
  }

  const subjectInfo = SUBJECT_MAP[correction.subject] || SUBJECT_MAP['other']
  const scorePercent = (correction.total_score / correction.max_score) * 100
  const questions = correction.questions_detail || []

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={() => navigate('/corrections')}
        className="flex items-center gap-2 text-slate-500 hover:text-slate-800 mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        返回批改历史
      </button>

      {/* 头部信息 */}
      <div className="card p-6 mb-6">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="font-display text-2xl font-bold text-slate-800 mb-2">
              {correction.exam_title || '试卷批改详情'}
            </h1>
            <div className="flex items-center gap-3 flex-wrap">
              <span className={`badge ${subjectInfo.bg} ${subjectInfo.color} border-0`}>
                {subjectInfo.label}
              </span>
              {correction.grade && (
                <span className="badge bg-slate-50 text-slate-600">
                  {correction.grade}
                </span>
              )}
              <span className="text-slate-500 text-sm flex items-center gap-1">
                <Clock className="w-4 h-4" />
                {new Date(correction.created_at).toLocaleString('zh-CN')}
              </span>
            </div>
          </div>
        </div>

        {/* 得分卡片 */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className={`p-4 rounded-lg ${scorePercent >= 60 ? 'bg-emerald-500/10 border border-emerald-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-600 text-sm">总得分</span>
              <Award className={`w-5 h-5 ${scorePercent >= 60 ? 'text-emerald-600' : 'text-red-600'}`} />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-4xl font-bold text-slate-800">{correction.total_score}</span>
              <span className="text-slate-500">/ {correction.max_score}</span>
            </div>
            <div className="mt-2">
              <div className="h-2 bg-slate-50 rounded-full overflow-hidden">
                <div
                  className={clsx(
                    "h-full transition-all",
                    scorePercent >= 60
                      ? "bg-primary-50 from-emerald-500 to-green-500"
                      : "bg-primary-50 from-red-500 to-orange-500"
                  )}
                  style={{ width: `${Math.min(100, scorePercent)}%` }}
                />
              </div>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-slate-50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-600 text-sm">正确率</span>
              <BarChart3 className="w-5 h-5 text-primary-600" />
            </div>
            <div className="text-4xl font-bold text-slate-800">
              {(correction.accuracy_rate * 100).toFixed(0)}%
            </div>
          </div>

          <div className="p-4 rounded-lg bg-emerald-500/10">
            <div className="flex items-center justify-between mb-2">
              <span className="text-emerald-600 text-sm">答对</span>
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            </div>
            <div className="text-4xl font-bold text-emerald-600">
              {correction.correct_count}
            </div>
            <div className="text-xs text-emerald-600/70 mt-1">
              / {correction.question_count} 题
            </div>
          </div>

          <div className="p-4 rounded-lg bg-red-500/10">
            <div className="flex items-center justify-between mb-2">
              <span className="text-red-600 text-sm">答错</span>
              <XCircle className="w-5 h-5 text-red-600" />
            </div>
            <div className="text-4xl font-bold text-red-600">
              {correction.wrong_count}
            </div>
            <div className="text-xs text-red-600/70 mt-1">
              / {correction.question_count} 题
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧 - 图片和总体分析 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 原始与批改对比 */}
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-slate-800 font-semibold flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-primary-600" />
                试卷对比
              </h2>
              {correction.corrected_image_url && (
                <button
                  onClick={() => setCompareViewerOpen(true)}
                  className="btn-primary px-4 py-2 text-sm flex items-center gap-2"
                >
                  <ArrowLeftRight className="w-4 h-4" />
                  对比放大
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* 原始试卷 */}
              <div>
                <div className="text-slate-500 text-sm mb-2">📄 原始试卷</div>
                <div className="relative group cursor-pointer">
                  <img
                    src={correction.original_image_url}
                    alt="原始试卷"
                    className="w-full rounded-lg transition-all group-hover:brightness-110"
                    onClick={() => {
                      setViewerImage({ url: correction.original_image_url, title: '原始试卷' })
                      setViewerOpen(true)
                    }}
                  />
                  <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center rounded-lg">
                    <div className="p-3 bg-black/60 backdrop-blur-sm rounded-lg">
                      <Maximize2 className="w-7 h-7 text-white" />
                    </div>
                  </div>
                </div>
              </div>

              {/* 批改后试卷 */}
              {correction.corrected_image_url && (
                <div>
                  <div className="text-red-600 text-sm mb-2 flex items-center gap-1">
                    <CheckCircle2 className="w-4 h-4" />
                    批改后试卷
                  </div>
                  <div className="relative group cursor-pointer">
                    <img
                      src={correction.corrected_image_url}
                      alt="批改后试卷"
                      className="w-full rounded-lg transition-all group-hover:brightness-110"
                      onClick={() => {
                        setViewerImage({ url: correction.corrected_image_url, title: '批改后试卷' })
                        setViewerOpen(true)
                      }}
                    />
                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center rounded-lg">
                      <div className="p-3 bg-black/60 backdrop-blur-sm rounded-lg">
                        <Maximize2 className="w-7 h-7 text-white" />
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 总体分析 */}
          {correction.overall_analysis && (
            <div className="card p-6">
              <h2 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                <FileCheck className="w-5 h-5 text-primary-600" />
                AI 总体分析
              </h2>
              <div className="bg-slate-50 rounded-lg p-4">
                <p className="text-slate-600 leading-relaxed whitespace-pre-wrap">
                  {correction.overall_analysis}
                </p>
              </div>
            </div>
          )}

          {/* 题目详情列表 */}
          {questions.length > 0 && (
            <div className="card p-6">
              <h2 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-cyan-600" />
                题目详情 ({questions.length} 题)
              </h2>
              <div className="space-y-4">
                {questions.map((q, index) => (
                  <div
                    key={index}
                    className={clsx(
                      "p-4 rounded-lg border",
                      q.is_correct
                        ? "bg-emerald-500/5 border-emerald-500/30"
                        : "bg-red-500/5 border-red-500/30"
                    )}
                  >
                    {/* 题目头部 */}
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <span className={clsx(
                          "w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold",
                          q.is_correct
                            ? "bg-emerald-500 text-white"
                            : "bg-red-500 text-white"
                        )}>
                          {q.question_number}
                        </span>
                        <span className="text-slate-500 text-sm">{q.question_type}</span>
                        {q.knowledge_points && q.knowledge_points.length > 0 && (
                          <div className="flex gap-1 ml-2">
                            {q.knowledge_points.slice(0, 2).map((kp, i) => (
                              <span key={i} className="badge-accent text-xs">
                                {kp}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={clsx(
                          "text-lg font-bold",
                          q.is_correct ? "text-emerald-600" : "text-red-600"
                        )}>
                          {q.score}/{q.max_score}
                        </span>
                        {q.is_correct ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                        ) : (
                          <XCircle className="w-5 h-5 text-red-600" />
                        )}
                      </div>
                    </div>

                    {/* 题目内容 */}
                    <div className="mb-3">
                      <div className="text-slate-500 text-xs mb-1">题目:</div>
                      <div className="bg-slate-50 rounded-lg p-3">
                        <p className="text-slate-800 text-sm">{q.question_text}</p>
                      </div>
                    </div>

                    {/* 答案对比 */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {/* 学生答案 */}
                      <div>
                        <div className="text-red-600 text-xs mb-1">学生答案:</div>
                        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                          <p className="text-slate-600 text-sm">{q.student_answer || '未作答'}</p>
                        </div>
                      </div>

                      {/* 正确答案 */}
                      {q.correct_answer && (
                        <div>
                          <div className="text-emerald-600 text-xs mb-1">正确答案:</div>
                          <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-3">
                            <p className="text-slate-600 text-sm">{q.correct_answer}</p>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 错因分析 */}
                    {!q.is_correct && q.error_analysis && (
                      <div className="mt-3">
                        <div className="text-amber-600 text-xs mb-1 flex items-center gap-1">
                          <Target className="w-3 h-3" />
                          错因分析:
                        </div>
                        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3">
                          <p className="text-slate-600 text-sm">{q.error_analysis}</p>
                        </div>
                      </div>
                    )}

                    {/* 解题步骤 */}
                    {q.solution_steps && q.solution_steps.length > 0 && (
                      <div className="mt-3">
                        <div className="text-primary-600 text-xs mb-2">解题步骤:</div>
                        <ol className="space-y-1 ml-4">
                          {q.solution_steps.map((step, i) => (
                            <li key={i} className="text-slate-600 text-sm list-decimal">
                              {step}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 右侧 - 薄弱点和建议 */}
        <div className="space-y-6">
          {/* 薄弱知识点 */}
          {correction.weak_points && correction.weak_points.length > 0 && (
            <div className="card p-6">
              <h3 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                <Target className="w-5 h-5 text-amber-600" />
                薄弱知识点
              </h3>
              <div className="space-y-2">
                {correction.weak_points.map((point, index) => (
                  <div
                    key={index}
                    className="flex items-center gap-2 p-3 bg-amber-500/10 rounded-lg"
                  >
                    <span className="w-6 h-6 bg-amber-500/30 text-amber-600 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0">
                      {index + 1}
                    </span>
                    <span className="text-amber-600 text-sm">{point}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 改进建议 */}
          {correction.improvement_suggestions && correction.improvement_suggestions.length > 0 && (
            <div className="card p-6">
              <h3 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-emerald-600" />
                改进建议
              </h3>
              <ul className="space-y-3">
                {correction.improvement_suggestions.map((suggestion, index) => (
                  <li key={index} className="flex items-start gap-3">
                    <span className="w-6 h-6 bg-emerald-500/20 text-emerald-600 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5">
                      {index + 1}
                    </span>
                    <span className="text-slate-600 text-sm leading-relaxed">
                      {suggestion}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 统计信息 */}
          <div className="card p-6">
            <h3 className="text-slate-800 font-semibold mb-4">统计信息</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">题目总数</span>
                <span className="text-slate-800 font-medium">{correction.question_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">答对题数</span>
                <span className="text-emerald-600 font-medium">{correction.correct_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">答错题数</span>
                <span className="text-red-600 font-medium">{correction.wrong_count}</span>
              </div>
              <div className="flex justify-between pt-3 border-t border-slate-200">
                <span className="text-slate-500">批改时间</span>
                <span className="text-slate-800 font-medium">
                  {new Date(correction.created_at).toLocaleDateString('zh-CN')}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 单图查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />

      {/* 对比查看器 */}
      <ImageCompareViewer
        isOpen={compareViewerOpen}
        onClose={() => setCompareViewerOpen(false)}
        leftImage={{ url: correction.original_image_url, title: '原始试卷' }}
        rightImage={{ url: correction.corrected_image_url, title: '批改后试卷' }}
      />
    </div>
  )
}
