import { useState } from 'react'
import { useParams, useNavigate, Link, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { questionApi, feedbackApi } from '../lib/api'
import ReactMarkdown from 'react-markdown'
import {
  ArrowLeft,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  Loader2,
  BookOpen,
  Target,
  Lightbulb,
  CheckCircle,
  Image as ImageIcon,
  Maximize2
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import ImageViewer from '../components/ImageViewer'

export default function QuestionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const [sqAnswerLoading, setSqAnswerLoading] = useState({})
  const [sqAnswerError, setSqAnswerError] = useState({})

  const urlSubject = (() => {
    try {
      const s = new URLSearchParams(location.search || '').get('subject')
      return s ? String(s) : null
    } catch {
      return null
    }
  })()

  const { data, isLoading, error } = useQuery({
    queryKey: ['question', id, urlSubject],
    queryFn: () => questionApi.get(id, urlSubject || undefined),
  })

  const reanalyzeMutation = useMutation({
    mutationFn: () => questionApi.reanalyze(id, urlSubject || undefined),
    onSuccess: () => {
      toast.success('重新分析已开始')
      // Poll for updates
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['question', id, urlSubject] })
      }, 5000)
    },
    onError: () => {
      toast.error('重新分析失败')
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: feedbackApi.create,
    onSuccess: () => {
      toast.success('感谢您的反馈！')
    },
  })

  // IMPORTANT: this hook must be called unconditionally (before any early returns),
  // otherwise React will detect a hook order change between loading/error renders and data renders.
  const fetchSuggestedAnswerMutation = useMutation({
    mutationFn: ({ index, subject }) => questionApi.getSuggestedQuestionAnswer(id, index, subject),
    onSuccess: (resp, vars) => {
      const idx = vars?.index
      const sq = resp?.data?.suggested_question
      if (typeof idx !== 'number' || !sq) return
      queryClient.setQueryData(['question', id, urlSubject], (old) => {
        if (!old || !old.data) return old
        const next = { ...old, data: { ...old.data } }
        const list = Array.isArray(next.data.suggested_questions) ? [...next.data.suggested_questions] : []
        if (idx >= 0 && idx < list.length) {
          list[idx] = sq
          next.data.suggested_questions = list
        }
        return next
      })
      setSqAnswerLoading((m) => ({ ...m, [idx]: false }))
      setSqAnswerError((m) => ({ ...m, [idx]: null }))
    },
    onError: (err, vars) => {
      const idx = vars?.index
      setSqAnswerLoading((m) => ({ ...m, [idx]: false }))
      const msg = err?.response?.data?.detail || err?.message || '生成答案失败'
      setSqAnswerError((m) => ({ ...m, [idx]: msg }))
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (error || !data?.data) {
    return (
      <div className="card p-12 text-center">
        <BookOpen className="w-16 h-16 text-slate-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-slate-800 mb-2">题目不存在</h3>
        <p className="text-slate-500 mb-4">该题目可能已被删除</p>
        <button onClick={() => navigate('/questions')} className="btn-primary">
          返回错题本
        </button>
      </div>
    )
  }

  const question = data.data

  const safeDateText = (v) => {
    if (!v) return '-'
    try {
      const d = new Date(v)
      if (Number.isNaN(d.getTime())) return '-'
      return d.toLocaleDateString('zh-CN')
    } catch {
      return '-'
    }
  }

  const safeArrayStrings = (arr) => {
    if (!Array.isArray(arr)) return []
    return arr
      .map((x) => {
        if (x == null) return ''
        if (typeof x === 'string') return x
        if (typeof x === 'number' || typeof x === 'boolean') return String(x)
        if (typeof x === 'object') {
          // best-effort for legacy/object formats
          if (typeof x.name === 'string') return x.name
          try {
            return JSON.stringify(x)
          } catch {
            return String(x)
          }
        }
        return String(x)
      })
      .map((s) => String(s).trim())
      .filter(Boolean)
  }

  const subjectText = typeof question.subject === 'string' ? question.subject : String(question.subject || '')
  const difficultyValue = typeof question.difficulty === 'string' ? question.difficulty : 'medium'
  const knowledgePoints = safeArrayStrings(question.knowledge_points)
  const tags = safeArrayStrings(question.tags)
  const imageUrls = Array.isArray(question.image_urls)
    ? question.image_urls.filter((u) => typeof u === 'string' && u.trim())
    : []

  const normalizeSuggestedQuestions = (v) => {
    if (!Array.isArray(v)) return []
    return v
      .map((item) => {
        if (item == null) return null
        if (typeof item === 'string') {
          const s = item.trim()
          if (!s) return null
          return { content: s, answer: '', difficulty: 'medium', explanation: null }
        }
        if (typeof item === 'object') {
          const content = (typeof item.content === 'string' && item.content.trim())
            ? item.content.trim()
            : (typeof item.question === 'string' && item.question.trim())
              ? item.question.trim()
              : (typeof item.title === 'string' && item.title.trim())
                ? item.title.trim()
                : ''
          if (!content) return null
          const answer = typeof item.answer === 'string' ? item.answer : (typeof item.solution === 'string' ? item.solution : '')
          const difficulty = typeof item.difficulty === 'string' ? item.difficulty : 'medium'
          const explanation = typeof item.explanation === 'string' ? item.explanation : null
          return { ...item, content, answer, difficulty, explanation }
        }
        return null
      })
      .filter(Boolean)
  }

  const suggestedQuestions = normalizeSuggestedQuestions(question.suggested_questions)

  const answerMeta = (question && typeof question === 'object') ? question.answer_sources : null
  const answerSources = answerMeta && typeof answerMeta === 'object' ? (answerMeta.answer_sources || {}) : {}
  const gradingMeta = answerMeta && typeof answerMeta === 'object' ? (answerMeta.grading || {}) : {}
  const teacherMarkedAnswer = typeof answerSources.teacher_marked_answer === 'string' ? answerSources.teacher_marked_answer : ''
  const modelInferredAnswer = typeof answerSources.model_inferred_answer === 'string' ? answerSources.model_inferred_answer : ''
  const decidedBy = typeof gradingMeta.decided_by === 'string' ? gradingMeta.decided_by : ''
  const teacherMark = gradingMeta && typeof gradingMeta === 'object' ? (gradingMeta.teacher_mark || null) : null
  const teacherMarkText = (() => {
    if (!teacherMark || typeof teacherMark !== 'object') return ''
    const mark = typeof teacherMark.mark === 'string' ? teacherMark.mark : ''
    const color = typeof teacherMark.color === 'string' ? teacherMark.color : ''
    const evi = typeof teacherMark.evidence === 'string' ? teacherMark.evidence : ''
    const ic = teacherMark.is_correct
    const icText = (ic === true) ? '正确' : (ic === false) ? '错误' : ''
    const parts = []
    if (icText) parts.push(icText)
    if (mark) parts.push(`标记:${mark}`)
    if (color) parts.push(`颜色:${color}`)
    if (evi) parts.push(`证据:${evi}`)
    return parts.join(' · ')
  })()

  const ensureSuggestedAnswer = (sq, index) => {
    const hasAnswer = typeof sq?.answer === 'string' && sq.answer.trim().length > 0
    if (hasAnswer) return
    if (sqAnswerLoading[index]) return
    setSqAnswerLoading((m) => ({ ...m, [index]: true }))
    setSqAnswerError((m) => ({ ...m, [index]: null }))
    fetchSuggestedAnswerMutation.mutate({ index, subject: urlSubject || subjectText })
  }

  const handleFeedback = (type) => {
    feedbackMutation.mutate({
      question_id: question.id,
      feedback_type: type,
    })
  }

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-slate-500 hover:text-slate-800 mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        返回
      </button>

      {/* Main content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Question info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Title and meta */}
          <div className="card p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <h1 className="font-display text-2xl font-bold text-slate-800">
                {question.title || '错题详情'}
              </h1>
              <button
                onClick={() => reanalyzeMutation.mutate()}
                disabled={reanalyzeMutation.isPending}
                className="btn-secondary flex items-center gap-2 text-sm"
              >
                {reanalyzeMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                重新分析
              </button>
            </div>

            <div className="flex items-center gap-3 flex-wrap mb-6">
              <span className="badge-primary">
                {subjectText}
              </span>
              <span className={clsx(
                'badge',
                difficultyValue === 'easy' && 'bg-emerald-500/20 text-emerald-600 border border-emerald-500/30',
                difficultyValue === 'medium' && 'bg-amber-500/20 text-amber-600 border border-amber-500/30',
                difficultyValue === 'hard' && 'bg-red-500/20 text-red-600 border border-red-500/30',
              )}>
                {difficultyValue === 'easy' ? '简单' :
                 difficultyValue === 'medium' ? '中等' : '困难'}
              </span>
              {knowledgePoints.map((kp) => (
                <span key={kp} className="badge-accent">
                  {kp}
                </span>
              ))}
            </div>

            {/* Question content */}
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-slate-500 mb-2 flex items-center gap-2">
                  <BookOpen className="w-4 h-4" />
                  题目内容
                </h3>
                <div className="bg-slate-50 rounded-lg p-4">
                  <p className="text-slate-800 whitespace-pre-wrap">{question.content}</p>
                </div>
              </div>

              {/* 题目图片 */}
              {imageUrls.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-500 mb-2 flex items-center gap-2">
                    <ImageIcon className="w-4 h-4" />
                    题目图片
                  </h3>
                  {question.source_image_id && (
                    <div className="mb-3">
                      <Link
                        to={`/questions/image/${question.source_image_id}`}
                        className="inline-flex items-center gap-2 text-primary-600 hover:text-primary-600 text-sm"
                      >
                        查看本次上传图片中的全部题目
                      </Link>
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-4">
                    {imageUrls.map((url, index) => (
                      <div
                        key={index}
                        className="relative group cursor-pointer overflow-hidden rounded-lg bg-slate-50 border border-slate-200 hover:border-primary-500/50 transition-all"
                        onClick={() => {
                          setViewerImage({
                            url: url.startsWith('http') ? url : `/api/v1${url}`,
                            title: `题目图片 ${index + 1}`
                          })
                          setViewerOpen(true)
                        }}
                      >
                        <img
                          src={url.startsWith('http') ? url : `/api/v1${url}`}
                          alt={`题目图片 ${index + 1}`}
                          className="w-full h-40 object-cover group-hover:scale-105 transition-transform duration-300"
                        />
                        {/* 悬浮放大提示 */}
                        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <div className="text-center">
                            <Maximize2 className="w-8 h-8 text-white mx-auto mb-2" />
                            <p className="text-slate-800 text-sm font-medium">点击放大</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {question.student_answer && (
                <div>
                  <h3 className="text-sm font-medium text-red-600 mb-2">我的答案</h3>
                  <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
                    <p className="text-slate-600 whitespace-pre-wrap">{question.student_answer}</p>
                  </div>
                </div>
              )}

              {(question.correct_answer || teacherMarkedAnswer || modelInferredAnswer) && (
                <div>
                  <h3 className="text-sm font-medium text-emerald-600 mb-2 flex items-center gap-2">
                    <CheckCircle className="w-4 h-4" />
                    正确答案（判定依据）
                  </h3>
                  <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-4">
                    {teacherMarkedAnswer ? (
                      <div className="space-y-2">
                        <p className="text-slate-700 whitespace-pre-wrap">{teacherMarkedAnswer}</p>
                        <p className="text-slate-500 text-xs">来源：老师批改/学生标注</p>
                      </div>
                    ) : question.correct_answer ? (
                      <div className="space-y-2">
                        <p className="text-slate-700 whitespace-pre-wrap">{question.correct_answer}</p>
                        <p className="text-slate-500 text-xs">来源：系统识别</p>
                      </div>
                    ) : (
                      <p className="text-slate-500 text-sm">未识别到可用于判定的“老师批改/标注正确答案”</p>
                    )}

                    {modelInferredAnswer && (
                      <div className="mt-3 pt-3 border-t border-emerald-500/20">
                        <p className="text-slate-600 whitespace-pre-wrap">{modelInferredAnswer}</p>
                        <p className="text-slate-500 text-xs mt-1">模型参考答案（仅供参考）</p>
                      </div>
                    )}

                    {decidedBy && (
                      <p className="text-slate-500 text-xs mt-3">
                        判定方式：{decidedBy === 'teacher_marked' ? '老师批改/标注' :
                          decidedBy === 'teacher_mark' ? '卷面批改符号（√/×）' :
                          decidedBy === 'model_inferred' ? '模型推断' :
                          decidedBy === 'score' ? '得分/满分' : '未知'}
                      </p>
                    )}

                    {teacherMarkText && (
                      <p className="text-slate-500 text-xs mt-2">
                        卷面批改：{teacherMarkText}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Error analysis */}
          {question.error_analysis && (
            <div className="card p-6">
              <h2 className="font-semibold text-slate-800 text-lg mb-4 flex items-center gap-2">
                <Target className="w-5 h-5 text-primary-600" />
                AI错因分析
              </h2>
              <div className="prose-dark">
                <ReactMarkdown>{typeof question.error_analysis === 'string' ? question.error_analysis : String(question.error_analysis || '')}</ReactMarkdown>
              </div>

              {/* Feedback */}
              <div className="flex items-center gap-4 mt-6 pt-4 border-t border-slate-200">
                <span className="text-slate-500 text-sm">这个分析对你有帮助吗？</span>
                <button
                  onClick={() => handleFeedback('helpful')}
                  className="flex items-center gap-2 text-emerald-600 hover:text-emerald-600 transition-colors"
                >
                  <ThumbsUp className="w-4 h-4" />
                  有帮助
                </button>
                <button
                  onClick={() => handleFeedback('not_helpful')}
                  className="flex items-center gap-2 text-slate-500 hover:text-red-600 transition-colors"
                >
                  <ThumbsDown className="w-4 h-4" />
                  没帮助
                </button>
              </div>
            </div>
          )}

          {/* Suggested questions */}
          {suggestedQuestions.length > 0 && (
            <div className="card p-6">
              <h2 className="font-semibold text-slate-800 text-lg mb-4 flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-cyan-600" />
                举一反三
              </h2>
              <div className="space-y-4">
                {suggestedQuestions.map((sq, index) => {
                  const sqDifficulty = typeof sq?.difficulty === 'string' ? sq.difficulty : 'medium'
                  return (
                  <div key={index} className="bg-slate-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-medium text-primary-600">
                        练习题 {index + 1}
                      </span>
                      <span className={clsx(
                        'text-xs px-2 py-0.5 rounded-full',
                          sqDifficulty === 'easy' && 'bg-emerald-500/20 text-emerald-600',
                          sqDifficulty === 'medium' && 'bg-amber-500/20 text-amber-600',
                          sqDifficulty === 'hard' && 'bg-red-500/20 text-red-600',
                      )}>
                          {sqDifficulty === 'easy' ? '简单' :
                           sqDifficulty === 'medium' ? '中等' : '困难'}
                      </span>
                    </div>
                      <p className="text-slate-800 mb-3">{typeof sq?.content === 'string' ? sq.content : String(sq?.content || '')}</p>
                    <details className="group">
                      <summary
                        className="text-primary-600 text-sm cursor-pointer hover:text-primary-600"
                        onClick={() => ensureSuggestedAnswer(sq, index)}
                      >
                        查看答案
                      </summary>
                      <div className="mt-2 pt-2 border-t border-slate-200">
                        {sqAnswerLoading[index] ? (
                          <p className="text-slate-500 text-sm">正在生成答案...</p>
                        ) : (typeof sq.answer === 'string' && sq.answer.trim()) ? (
                          <p className="text-slate-600 text-sm whitespace-pre-wrap">{sq.answer}</p>
                        ) : sqAnswerError[index] ? (
                          <p className="text-red-600 text-sm">{sqAnswerError[index]}</p>
                        ) : (
                          <p className="text-slate-500 text-sm">暂无答案（点击“查看答案”将自动生成）</p>
                        )}
                        {sq.explanation && (
                          <p className="text-slate-500 text-sm mt-2 whitespace-pre-wrap">{sq.explanation}</p>
                        )}
                      </div>
                    </details>
                  </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Meta info */}
          <div className="card p-6">
            <h3 className="font-semibold text-slate-800 mb-4">题目信息</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">创建时间</span>
                <span className="text-slate-800">
                  {safeDateText(question.created_at)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">复习次数</span>
                <span className="text-slate-800">{question.review_count || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">掌握程度</span>
                <span className="text-slate-800">
                  {((question.mastery_level || 0) * 100).toFixed(0)}%
                </span>
              </div>
              {question.source && (
                <div className="flex justify-between">
                  <span className="text-slate-500">来源</span>
                  <span className="text-slate-800">{question.source}</span>
                </div>
              )}
              {question.chapter && (
                <div className="flex justify-between">
                  <span className="text-slate-500">章节</span>
                  <span className="text-slate-800">{question.chapter}</span>
                </div>
              )}
            </div>
          </div>

          {/* Tags */}
          {question.tags?.length > 0 && (
            <div className="card p-6">
              <h3 className="font-semibold text-slate-800 mb-4">标签</h3>
              <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <span key={tag} className="badge-accent">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 图片查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />
    </div>
  )
}
