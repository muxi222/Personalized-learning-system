import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { imageFilesApi } from '../lib/api'
import { ArrowLeft, Image as ImageIcon, CheckCircle, XCircle, HelpCircle, Maximize2, ArrowRight, Trash2 } from 'lucide-react'
import ImageViewer from '../components/ImageViewer'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function ImageQuestionGroup() {
  const { imageId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })

  const { data, isLoading, error } = useQuery({
    queryKey: ['image-questions', imageId],
    queryFn: () => imageFilesApi.getQuestions(imageId),
  })

  const deleteGroupMutation = useMutation({
    mutationFn: () => imageFilesApi.deleteGroup(imageId),
    onSuccess: (resp) => {
      const { deleted_questions } = resp?.data || {}
      toast.success(`已删除该图片下 ${deleted_questions ?? 0} 道错题`)
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.removeQueries({ queryKey: ['image-questions', imageId] })
      navigate(-1)
    },
    onError: () => {
      toast.error('删除失败')
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">加载中...</div>
      </div>
    )
  }

  if (error || !data?.data) {
    return (
      <div className="card p-12 text-center">
        <h3 className="text-lg font-medium text-white mb-2">加载失败</h3>
        <p className="text-slate-400 mb-4">无法获取该图片对应的题目列表</p>
        <button onClick={() => navigate(-1)} className="btn-primary">
          返回
        </button>
      </div>
    )
  }

  const payload = data.data
  const { image_url, questions } = payload

  const coerceBool = (v) => {
    if (v === true || v === false) return v
    if (v === 1 || v === 0) return Boolean(v)
    if (typeof v === 'string') {
      const s = v.trim().toLowerCase()
      if (['true', '1', 'yes', 'y', 'correct', 'right'].includes(s)) return true
      if (['false', '0', 'no', 'n', 'wrong', 'incorrect'].includes(s)) return false
    }
    return null
  }

  const inferIsCorrect = (q) => {
    const v = coerceBool(q?.is_correct)
    if (v === true || v === false) return v
    if (typeof q?.score === 'number' && typeof q?.max_score === 'number' && q.max_score > 0) {
      return q.score >= q.max_score
    }
    return null
  }

  const computedStats = (questions || []).reduce(
    (acc, q) => {
      const v = inferIsCorrect(q)
      if (v === true) acc.correct += 1
      else if (v === false) acc.wrong += 1
      else acc.unknown += 1
      acc.total += 1
      return acc
    },
    { total: 0, correct: 0, wrong: 0, unknown: 0 }
  )

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-slate-400 hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        返回错题本
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Uploaded image */}
          <div className="card p-6">
            <div className="flex items-center justify-between gap-4 mb-4">
              <h1 className="font-display text-2xl font-bold text-white flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-primary-300" />
                本次上传图片
              </h1>
              <div className="flex items-center gap-2">
                <button
                  className="btn-secondary flex items-center gap-2 text-sm"
                  onClick={() => {
                    setViewerImage({ url: image_url, title: '上传图片' })
                    setViewerOpen(true)
                  }}
                >
                  <Maximize2 className="w-4 h-4" />
                  放大查看
                </button>
                <button
                  className="bg-red-500/20 hover:bg-red-500/30 text-red-400 px-3 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 flex items-center gap-2"
                  disabled={deleteGroupMutation.isPending}
                  onClick={() => {
                    if (!confirm('确定要删除这张图片下的所有错题吗？此操作不可恢复。')) return
                    deleteGroupMutation.mutate()
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                  {deleteGroupMutation.isPending ? '删除中...' : '删除本图错题'}
                </button>
              </div>
            </div>

            <div
              className="rounded-xl overflow-hidden bg-slate-800/50 border border-slate-700/50 cursor-pointer hover:border-primary-500/50 transition-all"
              onClick={() => {
                setViewerImage({ url: image_url, title: '上传图片' })
                setViewerOpen(true)
              }}
            >
              <img src={image_url} alt="上传图片" className="w-full max-h-[420px] object-contain bg-black/20" />
            </div>
          </div>

          {/* Questions list */}
          <div className="card p-6">
            <div className="flex items-center justify-between gap-4 mb-4">
              <h2 className="text-lg font-semibold text-white">该图片中的题目</h2>
              <div className="text-slate-400 text-sm">共 {questions?.length || 0} 题</div>
            </div>

            <div className="space-y-3">
              {(questions || []).map((q) => (
                (() => {
                  const isCorrect = inferIsCorrect(q)
                  return (
                <Link
                  key={q.id}
                  to={`/questions/${q.id}${q.subject ? `?subject=${encodeURIComponent(q.subject)}` : ''}`}
                  className="block rounded-lg bg-slate-800/40 hover:bg-slate-800/60 border border-slate-700/40 hover:border-primary-500/40 transition-all p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-slate-300 text-xs">
                          {q.upload_index ? `第 ${q.upload_index} 题` : `题目 ${q.id}`}
                        </span>
                        <span
                          className={clsx(
                            'text-xs px-2 py-0.5 rounded-full border',
                            isCorrect === true && 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
                            isCorrect === false && 'bg-red-500/10 text-red-300 border-red-500/30',
                            isCorrect == null && 'bg-slate-500/10 text-slate-300 border-slate-500/30'
                          )}
                        >
                          {isCorrect === true ? '正确' : isCorrect === false ? '错误' : '未知'}
                        </span>
                        {typeof q.score === 'number' && typeof q.max_score === 'number' && (
                          <span className="text-slate-400 text-xs">
                            {q.score}/{q.max_score}
                          </span>
                        )}
                      </div>
                      <div className="text-white text-sm font-medium line-clamp-1">
                        {q.title || (q.content ? q.content.slice(0, 60) : '题目内容')}
                      </div>
                      <div className="text-slate-400 text-xs line-clamp-2 mt-1">{q.content}</div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0 mt-1" />
                  </div>
                </Link>
                  )
                })()
              ))}
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="space-y-6">
          <div className="card p-6">
            <h3 className="text-sm font-medium text-slate-400 mb-4">统计</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-slate-300">总题数</span>
                <span className="text-white font-semibold">{computedStats.total}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-emerald-300 flex items-center gap-2">
                  <CheckCircle className="w-4 h-4" /> 正确
                </span>
                <span className="text-emerald-200 font-semibold">{computedStats.correct}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-red-300 flex items-center gap-2">
                  <XCircle className="w-4 h-4" /> 错误
                </span>
                <span className="text-red-200 font-semibold">{computedStats.wrong}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-300 flex items-center gap-2">
                  <HelpCircle className="w-4 h-4" /> 未知
                </span>
                <span className="text-slate-200 font-semibold">{computedStats.unknown}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />
    </div>
  )
}


