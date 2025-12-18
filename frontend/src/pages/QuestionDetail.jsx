import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
import { clsx } from 'clsx'
import ImageViewer from '../components/ImageViewer'

export default function QuestionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })

  const { data, isLoading, error } = useQuery({
    queryKey: ['question', id],
    queryFn: () => questionApi.get(id),
  })

  const reanalyzeMutation = useMutation({
    mutationFn: () => questionApi.reanalyze(id),
    onSuccess: () => {
      toast.success('重新分析已开始')
      // Poll for updates
      setTimeout(() => {
        queryClient.invalidateQueries(['question', id])
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-primary-400 animate-spin" />
      </div>
    )
  }

  if (error || !data?.data) {
    return (
      <div className="card p-12 text-center">
        <BookOpen className="w-16 h-16 text-slate-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-white mb-2">题目不存在</h3>
        <p className="text-slate-400 mb-4">该题目可能已被删除</p>
        <button onClick={() => navigate('/questions')} className="btn-primary">
          返回错题本
        </button>
      </div>
    )
  }

  const question = data.data

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
        className="flex items-center gap-2 text-slate-400 hover:text-white mb-6 transition-colors"
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
              <h1 className="font-display text-2xl font-bold text-white">
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
                {question.subject}
              </span>
              <span className={clsx(
                'badge',
                question.difficulty === 'easy' && 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
                question.difficulty === 'medium' && 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
                question.difficulty === 'hard' && 'bg-red-500/20 text-red-300 border border-red-500/30',
              )}>
                {question.difficulty === 'easy' ? '简单' : 
                 question.difficulty === 'medium' ? '中等' : '困难'}
              </span>
              {question.knowledge_points?.map((kp) => (
                <span key={kp} className="badge-accent">
                  {kp}
                </span>
              ))}
            </div>

            {/* Question content */}
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-2">
                  <BookOpen className="w-4 h-4" />
                  题目内容
                </h3>
                <div className="bg-slate-800/50 rounded-xl p-4">
                  <p className="text-white whitespace-pre-wrap">{question.content}</p>
                </div>
              </div>

              {/* 题目图片 */}
              {question.image_urls && question.image_urls.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-2">
                    <ImageIcon className="w-4 h-4" />
                    题目图片
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    {question.image_urls.map((url, index) => (
                      <div
                        key={index}
                        className="relative group cursor-pointer overflow-hidden rounded-xl bg-slate-800/50 border border-slate-700/50 hover:border-primary-500/50 transition-all"
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
                            <p className="text-white text-sm font-medium">点击放大</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {question.student_answer && (
                <div>
                  <h3 className="text-sm font-medium text-red-400 mb-2">我的答案</h3>
                  <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
                    <p className="text-slate-300 whitespace-pre-wrap">{question.student_answer}</p>
                  </div>
                </div>
              )}

              {question.correct_answer && (
                <div>
                  <h3 className="text-sm font-medium text-emerald-400 mb-2 flex items-center gap-2">
                    <CheckCircle className="w-4 h-4" />
                    正确答案
                  </h3>
                  <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4">
                    <p className="text-slate-300 whitespace-pre-wrap">{question.correct_answer}</p>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Error analysis */}
          {question.error_analysis && (
            <div className="card p-6">
              <h2 className="font-semibold text-white text-lg mb-4 flex items-center gap-2">
                <Target className="w-5 h-5 text-primary-400" />
                AI错因分析
              </h2>
              <div className="prose-dark">
                <ReactMarkdown>{question.error_analysis}</ReactMarkdown>
              </div>

              {/* Feedback */}
              <div className="flex items-center gap-4 mt-6 pt-4 border-t border-slate-800">
                <span className="text-slate-400 text-sm">这个分析对你有帮助吗？</span>
                <button
                  onClick={() => handleFeedback('helpful')}
                  className="flex items-center gap-2 text-emerald-400 hover:text-emerald-300 transition-colors"
                >
                  <ThumbsUp className="w-4 h-4" />
                  有帮助
                </button>
                <button
                  onClick={() => handleFeedback('not_helpful')}
                  className="flex items-center gap-2 text-slate-400 hover:text-red-400 transition-colors"
                >
                  <ThumbsDown className="w-4 h-4" />
                  没帮助
                </button>
              </div>
            </div>
          )}

          {/* Suggested questions */}
          {question.suggested_questions?.length > 0 && (
            <div className="card p-6">
              <h2 className="font-semibold text-white text-lg mb-4 flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-accent-400" />
                举一反三
              </h2>
              <div className="space-y-4">
                {question.suggested_questions.map((sq, index) => (
                  <div key={index} className="bg-slate-800/50 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-medium text-primary-400">
                        练习题 {index + 1}
                      </span>
                      <span className={clsx(
                        'text-xs px-2 py-0.5 rounded-full',
                        sq.difficulty === 'easy' && 'bg-emerald-500/20 text-emerald-300',
                        sq.difficulty === 'medium' && 'bg-amber-500/20 text-amber-300',
                        sq.difficulty === 'hard' && 'bg-red-500/20 text-red-300',
                      )}>
                        {sq.difficulty === 'easy' ? '简单' : 
                         sq.difficulty === 'medium' ? '中等' : '困难'}
                      </span>
                    </div>
                    <p className="text-white mb-3">{sq.content}</p>
                    <details className="group">
                      <summary className="text-primary-400 text-sm cursor-pointer hover:text-primary-300">
                        查看答案
                      </summary>
                      <div className="mt-2 pt-2 border-t border-slate-700">
                        <p className="text-slate-300 text-sm">{sq.answer}</p>
                        {sq.explanation && (
                          <p className="text-slate-400 text-sm mt-2">{sq.explanation}</p>
                        )}
                      </div>
                    </details>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Meta info */}
          <div className="card p-6">
            <h3 className="font-semibold text-white mb-4">题目信息</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-400">创建时间</span>
                <span className="text-white">
                  {new Date(question.created_at).toLocaleDateString('zh-CN')}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">复习次数</span>
                <span className="text-white">{question.review_count || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">掌握程度</span>
                <span className="text-white">
                  {((question.mastery_level || 0) * 100).toFixed(0)}%
                </span>
              </div>
              {question.source && (
                <div className="flex justify-between">
                  <span className="text-slate-400">来源</span>
                  <span className="text-white">{question.source}</span>
                </div>
              )}
              {question.chapter && (
                <div className="flex justify-between">
                  <span className="text-slate-400">章节</span>
                  <span className="text-white">{question.chapter}</span>
                </div>
              )}
            </div>
          </div>

          {/* Tags */}
          {question.tags?.length > 0 && (
            <div className="card p-6">
              <h3 className="font-semibold text-white mb-4">标签</h3>
              <div className="flex flex-wrap gap-2">
                {question.tags.map((tag) => (
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

