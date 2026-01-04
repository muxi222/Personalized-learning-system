import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X,
  ChevronLeft,
  ChevronRight,
  FileCheck,
  Image as ImageIcon,
  Target,
  Lightbulb,
  Award,
  BarChart3,
  Maximize2,
  Clock,
  CheckCircle2,
  XCircle,
  ArrowLeftRight,
  Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import ImageViewer from './ImageViewer'
import ImageCompareViewer from './ImageCompareViewer'
import { createApiClient } from '../lib/api'

/**
 * 创建批改记录 API 客户端
 */
const correctionsApi = {
  get: (id, subject = 'chinese') => {
    const client = createApiClient(subject)
    return client.get(`/corrections/${id}`).then(res => res.data)
  },
}

const SUBJECT_MAP = {
  'math': { label: '数学', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  'english': { label: '英语', color: 'text-green-400', bg: 'bg-green-500/10' },
  'physics': { label: '物理', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  'chemistry': { label: '化学', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  'chinese': { label: '语文', color: 'text-red-400', bg: 'bg-red-500/10' },
  'biology': { label: '生物', color: 'text-teal-400', bg: 'bg-teal-500/10' },
  'other': { label: '其他', color: 'text-slate-400', bg: 'bg-slate-500/10' },
}

/**
 * 批改详情抽屉
 * 从右侧滑出，支持上一个/下一个切换
 */
export default function CorrectionDetailDrawer({
  isOpen,
  onClose,
  correctionId,
  subject = 'chinese',  // 学科，用于路由到对应模块
  allIds = [],  // 所有批改记录的ID列表
  onNavigate,   // 切换到其他记录的回调
  listCorrection = null,  // 从列表接口获取的当前批改记录数据（优先使用，包含 original_image_url 和 corrected_image_url）
  allListCorrections = [],  // 所有列表数据，用于切换记录时获取对应的列表数据
}) {
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const [compareViewerOpen, setCompareViewerOpen] = useState(false)

  // 从列表数据中查找当前记录（优先使用列表数据中的图片URL）
  const currentListCorrection = allListCorrections.find(c => c.id === correctionId) || listCorrection

  // 获取详情（如果列表数据中没有完整信息，才调用详情接口）
  const { data: detailCorrection, isLoading } = useQuery({
    queryKey: ['correction', correctionId],
    queryFn: () => correctionsApi.get(correctionId, subject),
    enabled: isOpen && !!correctionId && !currentListCorrection,  // 如果有列表数据，就不调用详情接口
  })

  // 优先使用列表数据，如果没有则使用详情接口数据
  // 列表数据中的 original_image_url 和 corrected_image_url 是从 /api/v1/corrections/ 接口获取的
  const correction = currentListCorrection || detailCorrection

  // ESC 关闭
  useEffect(() => {
    const handleEsc = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [isOpen, onClose])

  // 阻止背景滚动
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = 'unset'
    }
    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [isOpen])

  // 获取当前索引
  const currentIndex = allIds.indexOf(correctionId)
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allIds.length - 1

  const handlePrev = () => {
    if (hasPrev && onNavigate) {
      onNavigate(allIds[currentIndex - 1])
    }
  }

  const handleNext = () => {
    if (hasNext && onNavigate) {
      onNavigate(allIds[currentIndex + 1])
    }
  }

  // 当 correctionId 变化时，如果 listCorrection 不存在，需要重新获取
  // 但这里我们优先使用传入的 listCorrection，所以不需要额外处理

  // 键盘导航
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e) => {
      if (e.key === 'ArrowLeft' && hasPrev) {
        handlePrev()
      } else if (e.key === 'ArrowRight' && hasNext) {
        handleNext()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, hasPrev, hasNext, currentIndex])

  if (!isOpen) return null

  const subjectInfo = correction ? SUBJECT_MAP[correction.subject] || SUBJECT_MAP['other'] : null
  const scorePercent = correction ? (correction.total_score / correction.max_score) * 100 : 0
  const questions = correction?.questions_detail || []

  return (
    <>
      {/* 遮罩层 */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-fade-in"
        onClick={onClose}
      />

      {/* 抽屉内容 */}
      <div className="fixed right-0 top-0 bottom-0 w-full lg:w-4/5 xl:w-3/4 bg-slate-950 z-50 overflow-y-auto shadow-2xl animate-slide-in-right">
        {/* 头部工具栏 */}
        <div className="sticky top-0 bg-slate-900/95 backdrop-blur-xl border-b border-slate-800 z-10">
          <div className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={onClose}
                className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>

              <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                <FileCheck className="w-6 h-6 text-primary-400" />
                批改详情
              </h2>

              {allIds.length > 1 && (
                <div className="flex items-center gap-2 ml-4">
                  <button
                    onClick={handlePrev}
                    disabled={!hasPrev}
                    className="p-2 hover:bg-slate-800 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="上一个 (←)"
                  >
                    <ChevronLeft className="w-5 h-5 text-slate-400" />
                  </button>

                  <span className="text-slate-500 text-sm">
                    {currentIndex + 1} / {allIds.length}
                  </span>

                  <button
                    onClick={handleNext}
                    disabled={!hasNext}
                    className="p-2 hover:bg-slate-800 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="下一个 (→)"
                  >
                    <ChevronRight className="w-5 h-5 text-slate-400" />
                  </button>
                </div>
              )}
            </div>

            <div className="text-slate-500 text-sm">
              ESC 关闭 · ← → 切换
            </div>
          </div>
        </div>

        {/* 内容区域 */}
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 text-primary-400 animate-spin" />
          </div>
        ) : correction ? (
          <div className="p-6">
            {/* 标题和元信息 */}
            <div className="mb-6">
              <h1 className="font-display text-3xl font-bold text-white mb-3">
                {correction.exam_title || '试卷批改详情'}
              </h1>
              <div className="flex items-center gap-3 flex-wrap">
                <span className={`badge ${subjectInfo.bg} ${subjectInfo.color} border-0`}>
                  {subjectInfo.label}
                </span>
                {correction.grade && (
                  <span className="badge bg-slate-700 text-slate-300">
                    {correction.grade}
                  </span>
                )}
                <span className="text-slate-500 text-sm flex items-center gap-1">
                  <Clock className="w-4 h-4" />
                  {new Date(correction.created_at).toLocaleString('zh-CN')}
                </span>
              </div>
            </div>

            {/* 统计卡片 */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              <div className={`p-4 rounded-xl ${scorePercent >= 60 ? 'bg-emerald-500/10 border border-emerald-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
                <div className="text-slate-300 text-sm mb-1">总得分</div>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold text-white">{correction.total_score}</span>
                  <span className="text-slate-400">/ {correction.max_score}</span>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-800/50">
                <div className="text-slate-300 text-sm mb-1">正确率</div>
                <div className="text-3xl font-bold text-white">
                  {(correction.accuracy_rate * 100).toFixed(0)}%
                </div>
              </div>

              <div className="p-4 rounded-xl bg-emerald-500/10">
                <div className="text-emerald-300 text-sm mb-1">答对</div>
                <div className="text-3xl font-bold text-emerald-400">{correction.correct_count}</div>
              </div>

              <div className="p-4 rounded-xl bg-red-500/10">
                <div className="text-red-300 text-sm mb-1">答错</div>
                <div className="text-3xl font-bold text-red-400">{correction.wrong_count}</div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* 左侧 */}
              <div className="lg:col-span-2 space-y-6">
                {/* 试卷对比 */}
                <div className="card p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-white font-semibold flex items-center gap-2">
                      <ImageIcon className="w-5 h-5 text-primary-400" />
                      试卷对比
                    </h3>
                    {correction.corrected_image_url && (
                      <button
                        onClick={() => setCompareViewerOpen(true)}
                        className="btn-primary px-3 py-2 text-sm flex items-center gap-2"
                      >
                        <ArrowLeftRight className="w-4 h-4" />
                        对比放大
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    {/* 原始 */}
                    <div>
                      <div className="text-slate-400 text-sm mb-2">📄 原始试卷</div>
                      <div className="relative group cursor-pointer">
                        <img
                          src={correction.original_image_url}
                          alt="原始试卷"
                          className="w-full rounded-xl transition-all group-hover:brightness-110"
                          onClick={() => {
                            setViewerImage({ url: correction.original_image_url, title: '原始试卷' })
                            setViewerOpen(true)
                          }}
                        />
                        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center rounded-xl">
                          <Maximize2 className="w-7 h-7 text-white" />
                        </div>
                      </div>
                    </div>

                    {/* 批改 */}
                    {correction.corrected_image_url && (
                      <div>
                        <div className="text-red-400 text-sm mb-2 flex items-center gap-1">
                          <CheckCircle2 className="w-4 h-4" />
                          批改后试卷
                        </div>
                        <div className="relative group cursor-pointer">
                          <img
                            src={correction.corrected_image_url}
                            alt="批改后试卷"
                            className="w-full rounded-xl transition-all group-hover:brightness-110"
                            onClick={() => {
                              setViewerImage({ url: correction.corrected_image_url, title: '批改后试卷' })
                              setViewerOpen(true)
                            }}
                          />
                          <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center rounded-xl">
                            <Maximize2 className="w-7 h-7 text-white" />
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* 总体分析 */}
                {correction.overall_analysis && (
                  <div className="card p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                      <FileCheck className="w-5 h-5 text-primary-400" />
                      AI 总体分析
                    </h3>
                    <div className="bg-slate-800/50 rounded-xl p-4">
                      <p className="text-slate-300 leading-relaxed whitespace-pre-wrap">
                        {correction.overall_analysis}
                      </p>
                    </div>
                  </div>
                )}

                {/* 题目详情 */}
                {questions.length > 0 && (
                  <div className="card p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                      <BarChart3 className="w-5 h-5 text-accent-400" />
                      题目详情 ({questions.length} 题)
                    </h3>
                    <div className="space-y-4 max-h-96 overflow-y-auto pr-2">
                      {questions.map((q, index) => (
                        <div
                          key={index}
                          className={clsx(
                            "p-4 rounded-xl border",
                            q.is_correct
                              ? "bg-emerald-500/5 border-emerald-500/30"
                              : "bg-red-500/5 border-red-500/30"
                          )}
                        >
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className={clsx(
                                "w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold",
                                q.is_correct ? "bg-emerald-500 text-white" : "bg-red-500 text-white"
                              )}>
                                {q.question_number}
                              </span>
                              <span className="text-slate-400 text-sm">{q.question_type}</span>
                            </div>
                            <span className={clsx("text-lg font-bold", q.is_correct ? "text-emerald-400" : "text-red-400")}>
                              {q.score}/{q.max_score}
                            </span>
                          </div>

                          <div className="text-white text-sm mb-2">
                            {q.question_text.length > 100 ? `${q.question_text.slice(0, 100)}...` : q.question_text}
                          </div>

                          {!q.is_correct && (
                            <div className="grid grid-cols-2 gap-2 text-xs">
                              <div className="bg-red-500/10 border border-red-500/30 rounded p-2">
                                <div className="text-red-400 mb-1">你的答案:</div>
                                <div className="text-slate-300">{q.student_answer || '未作答'}</div>
                              </div>
                              {q.correct_answer && (
                                <div className="bg-emerald-500/10 border border-emerald-500/30 rounded p-2">
                                  <div className="text-emerald-400 mb-1">正确答案:</div>
                                  <div className="text-slate-300">{q.correct_answer}</div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* 右侧 */}
              <div className="space-y-6">
                {/* 薄弱点 */}
                {correction?.weak_points && correction.weak_points.length > 0 && (
                  <div className="card p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                      <Target className="w-5 h-5 text-amber-400" />
                      薄弱知识点
                    </h3>
                    <div className="space-y-2">
                      {correction.weak_points.map((point, index) => (
                        <div key={index} className="flex items-center gap-2 p-3 bg-amber-500/10 rounded-lg">
                          <span className="w-6 h-6 bg-amber-500/30 text-amber-400 rounded-full flex items-center justify-center text-xs font-bold">
                            {index + 1}
                          </span>
                          <span className="text-amber-300 text-sm">{point}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 改进建议 */}
                {correction?.improvement_suggestions && correction.improvement_suggestions.length > 0 && (
                  <div className="card p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                      <Lightbulb className="w-5 h-5 text-emerald-400" />
                      改进建议
                    </h3>
                    <ul className="space-y-3">
                      {correction.improvement_suggestions.map((suggestion, index) => (
                        <li key={index} className="flex items-start gap-3">
                          <span className="w-6 h-6 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5">
                            {index + 1}
                          </span>
                          <span className="text-slate-300 text-sm leading-relaxed">{suggestion}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="p-12 text-center">
            <FileCheck className="w-16 h-16 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400">加载失败</p>
          </div>
        )}
      </div>

      {/* 图片查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />

      {/* 对比查看器 */}
      {correction && (
        <ImageCompareViewer
          isOpen={compareViewerOpen}
          onClose={() => setCompareViewerOpen(false)}
          leftImage={{ url: correction.original_image_url, title: '原始试卷' }}
          rightImage={{ url: correction.corrected_image_url, title: '批改后试卷' }}
        />
      )}
    </>
  )
}
