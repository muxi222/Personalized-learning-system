import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  FileCheck,
  TrendingUp,
  TrendingDown,
  Calendar,
  Filter,
  Image as ImageIcon,
  BarChart3,
  Target,
  Award,
  Clock,
  Maximize2,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Trash2,
} from 'lucide-react'
import { clsx } from 'clsx'
import toast from 'react-hot-toast'
import ImageViewer from '../components/ImageViewer'
import CorrectionDetailDrawer from '../components/CorrectionDetailDrawer'
import { createApiClient } from '../lib/api'

/**
 * 创建批改记录 API 客户端
 * 对于全部学科的请求，使用默认模块(default - port 6100)
 * 对于特定学科的请求，路由到对应模块
 */
const correctionsApi = {
  list: (params) => {
    // 如果指定了学科，使用该学科对应的模块；否则使用默认模块(default)
    const subject = params.subject || null  // null使用default模块
    const client = createApiClient(subject)
    return client.get('/corrections/', { params }).then(res => res.data)
  },

  get: (id, subject = null) => {
    const client = createApiClient(subject)
    return client.get(`/corrections/${id}`).then(res => res.data)
  },

  delete: (id, subject = null) => {
    const client = createApiClient(subject)
    return client.delete(`/corrections/${id}`)
  },

  getStatistics: (period, subject = null) => {
    const client = createApiClient(subject)
    return client.get(`/corrections/statistics/${period}`).then(res => res.data)
  },
}

// 10个学科 + 全部选项
const SUBJECTS = [
  { value: '', label: '全部学科' },
  // RPJ模块
  { value: 'chinese', label: '语文', color: 'text-red-400', bg: 'bg-red-500/10' },
  { value: 'english', label: '英语', color: 'text-green-400', bg: 'bg-green-500/10' },
  { value: 'politics', label: '政治', color: 'text-slate-400', bg: 'bg-slate-500/10' },
  // XMX模块
  { value: 'economics', label: '经济学', color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  // WZY模块
  { value: 'math', label: '数学', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  { value: 'physics', label: '物理', color: 'text-orange-400', bg: 'bg-orange-500/10' },
  // WZM模块
  { value: 'chemistry', label: '化学', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  // TONY模块
  { value: 'history', label: '历史', color: 'text-amber-700', bg: 'bg-amber-700/10' },
  { value: 'geography', label: '地理', color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
  { value: 'other', label: '其他', color: 'text-gray-400', bg: 'bg-gray-500/10' },
]

const PERIODS = [
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: 'quarter', label: '本季度' },
  { value: 'year', label: '本年' },
]

export default function CorrectionHistory() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [selectedSubject, setSelectedSubject] = useState('')
  const [selectedPeriod, setSelectedPeriod] = useState('week')
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const [selectedItems, setSelectedItems] = useState([])
  const [isSelectionMode, setIsSelectionMode] = useState(false)
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false)
  const [currentDetailId, setCurrentDetailId] = useState(null)
  const pageSize = 12

  // 获取批注列表
  const { data: listData, isLoading } = useQuery({
    queryKey: ['corrections', { page, page_size: pageSize, subject: selectedSubject }],
    queryFn: () => correctionsApi.list({ 
      page, 
      page_size: pageSize, 
      subject: selectedSubject || undefined 
    }),
  })

  // 获取统计数据
  const { data: stats } = useQuery({
    queryKey: ['correction-stats', selectedPeriod, selectedSubject],
    queryFn: () => {
      // 统计数据：如果选择了学科，向该学科模块请求；否则向default模块请求全部统计
      const subject = selectedSubject || null  // null使用default模块
      return correctionsApi.getStatistics(selectedPeriod, subject)
    },
  })

  const corrections = listData?.items || []
  const total = listData?.total || 0
  const totalPages = Math.ceil(total / pageSize)

  // 删除批改记录
  const deleteMutation = useMutation({
    mutationFn: ({ id, subject }) => correctionsApi.delete(id, subject),
    onSuccess: () => {
      queryClient.invalidateQueries(['corrections'])
      queryClient.invalidateQueries(['correction-stats'])
      toast.success('删除成功')
    },
    onError: () => {
      toast.error('删除失败')
    },
  })

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedItems.length === 0) {
      toast.error('请先选择要删除的记录')
      return
    }

    if (!confirm(`确定要删除 ${selectedItems.length} 条记录吗？`)) {
      return
    }

    for (const id of selectedItems) {
      // 找到对应的 correction 以获取 subject
      const correction = corrections.find(c => c.id === id)
      if (correction) {
        await deleteMutation.mutateAsync({ id, subject: correction.subject })
      }
    }

    setSelectedItems([])
    setIsSelectionMode(false)
    toast.success(`已删除 ${selectedItems.length} 条记录`)
  }

  // 切换选择
  const toggleSelection = (id) => {
    setSelectedItems(prev => 
      prev.includes(id) 
        ? prev.filter(item => item !== id)
        : [...prev, id]
    )
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedItems.length === corrections.length) {
      setSelectedItems([])
    } else {
      setSelectedItems(corrections.map(c => c.id))
    }
  }

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-12 h-12 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
            <FileCheck className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-bold text-white">
              AI批改历史
            </h1>
            <p className="text-slate-400">
              查看你的试卷批改记录和学习统计
            </p>
          </div>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="card p-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">批改次数</span>
            <FileCheck className="w-5 h-5 text-primary-400" />
          </div>
          <div className="text-3xl font-bold text-white">
            {stats?.total_corrections || 0}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {PERIODS.find(p => p.value === selectedPeriod)?.label}
          </div>
        </div>

        <div className="card p-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">题目总数</span>
            <BarChart3 className="w-5 h-5 text-accent-400" />
          </div>
          <div className="text-3xl font-bold text-white">
            {stats?.total_questions || 0}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            错 {stats?.total_wrong || 0} · 对 {stats?.total_correct || 0}
          </div>
        </div>

        <div className="card p-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">平均正确率</span>
            {stats?.avg_accuracy >= 0.6 ? (
              <TrendingUp className="w-5 h-5 text-emerald-400" />
            ) : (
              <TrendingDown className="w-5 h-5 text-amber-400" />
            )}
          </div>
          <div className="text-3xl font-bold text-white">
            {((stats?.avg_accuracy || 0) * 100).toFixed(0)}%
          </div>
          <div className={clsx(
            "text-xs mt-1",
            stats?.avg_accuracy >= 0.6 ? "text-emerald-400" : "text-amber-400"
          )}>
            {stats?.avg_accuracy >= 0.6 ? '继续保持' : '需要加油'}
          </div>
        </div>

        <div className="card p-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">平均得分</span>
            <Award className="w-5 h-5 text-amber-400" />
          </div>
          <div className="text-3xl font-bold text-white">
            {(stats?.avg_score || 0).toFixed(1)}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            满分通常为100分
          </div>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="card p-4 mb-6">
        <div className="flex flex-wrap items-center gap-4">
          {/* 时间周期 */}
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-slate-400" />
            <select
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(e.target.value)}
              className="input w-auto"
            >
              {PERIODS.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          {/* 学科筛选 */}
          <div className="flex items-center gap-2">
            <Filter className="w-5 h-5 text-slate-400" />
            <select
              value={selectedSubject}
              onChange={(e) => {
                setSelectedSubject(e.target.value)
                setPage(1)
              }}
              className="input w-auto"
            >
              {SUBJECTS.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex-1" />

          {/* 批量操作按钮 */}
          {isSelectionMode ? (
            <>
              <button
                onClick={toggleSelectAll}
                className="btn-secondary px-3 py-2 text-sm"
              >
                {selectedItems.length === corrections.length ? '取消全选' : '全选'}
              </button>
              <button
                onClick={handleBatchDelete}
                disabled={selectedItems.length === 0}
                className="bg-red-500/20 hover:bg-red-500/30 text-red-400 px-3 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4 inline mr-1" />
                删除 ({selectedItems.length})
              </button>
              <button
                onClick={() => {
                  setIsSelectionMode(false)
                  setSelectedItems([])
                }}
                className="btn-secondary px-3 py-2 text-sm"
              >
                取消
              </button>
            </>
          ) : (
            <button
              onClick={() => setIsSelectionMode(true)}
              className="btn-secondary px-3 py-2 text-sm flex items-center gap-1"
            >
              <Trash2 className="w-4 h-4" />
              批量管理
            </button>
          )}

          <div className="text-slate-400 text-sm">
            共 {total} 条记录
          </div>
        </div>
      </div>

      {/* 学科统计卡片 */}
      {stats?.subject_stats && Object.keys(stats.subject_stats).length > 0 && (
        <div className="card p-6 mb-6">
          <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
            <Target className="w-5 h-5 text-primary-400" />
            各学科表现
            <span className="text-slate-500 text-sm font-normal ml-auto">点击查看该学科的批改记录</span>
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {Object.entries(stats.subject_stats).map(([subj, data]) => {
              const subjectInfo = SUBJECTS.find(s => s.value === subj) || { label: subj, color: 'text-slate-400', bg: 'bg-slate-500/10' }
              const isSelected = selectedSubject === subj
              return (
                <button
                  key={subj}
                  onClick={() => {
                    setSelectedSubject(subj)
                    setPage(1)
                    // 滚动到列表区域
                    setTimeout(() => {
                      window.scrollTo({ top: 600, behavior: 'smooth' })
                    }, 100)
                  }}
                  className={clsx(
                    `${subjectInfo.bg} rounded-xl p-4 border transition-all text-left w-full`,
                    isSelected
                      ? 'border-primary-500 ring-2 ring-primary-500/50 scale-105'
                      : 'border-slate-700/50 hover:border-primary-500/50 hover:scale-102'
                  )}
                >
                  <div className={`${subjectInfo.color} font-medium mb-2 flex items-center justify-between`}>
                    <span>{subjectInfo.label}</span>
                    {isSelected && (
                      <CheckCircle2 className="w-4 h-4 text-primary-400" />
                    )}
                  </div>
                  <div className="text-sm space-y-1">
                    <div className="flex justify-between text-slate-300">
                      <span>批改:</span>
                      <span className="font-medium">{data.count}次</span>
                    </div>
                    <div className="flex justify-between text-slate-300">
                      <span>正确率:</span>
                      <span className={clsx(
                        "font-medium",
                        data.avg_accuracy >= 0.6 ? "text-emerald-400" : "text-amber-400"
                      )}>
                        {(data.avg_accuracy * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex justify-between text-red-400">
                      <span>错题:</span>
                      <span className="font-medium">{data.wrong_count}</span>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
          {selectedSubject && (
            <div className="mt-4 p-3 bg-primary-500/10 border border-primary-500/30 rounded-lg">
              <p className="text-primary-400 text-sm flex items-center gap-2">
                <Filter className="w-4 h-4" />
                当前筛选：{SUBJECTS.find(s => s.value === selectedSubject)?.label}
                <button
                  onClick={() => setSelectedSubject('')}
                  className="ml-auto text-xs hover:text-primary-300 underline"
                >
                  清除筛选
                </button>
              </p>
            </div>
          )}
        </div>
      )}

      {/* 列表标题 */}
      {corrections.length > 0 && (
        <div className="mb-4">
          <h2 className="text-white font-semibold text-xl flex items-center gap-2">
            <FileCheck className="w-5 h-5 text-primary-400" />
            {selectedSubject ? 
              `${SUBJECTS.find(s => s.value === selectedSubject)?.label}批改记录` : 
              '所有批改记录'
            }
            <span className="text-slate-500 text-base font-normal ml-2">
              ({corrections.length} / {total})
            </span>
          </h2>
        </div>
      )}

      {/* 批注记录列表 */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="card p-6 animate-pulse">
              <div className="h-40 bg-slate-700 rounded-xl mb-4" />
              <div className="h-5 bg-slate-700 rounded w-3/4 mb-2" />
              <div className="h-4 bg-slate-700 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : corrections.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {corrections.map((correction, index) => {
            const subjectInfo = SUBJECTS.find(s => s.value === correction.subject) || { label: correction.subject, color: 'text-slate-400', bg: 'bg-slate-500/10' }
            const scorePercent = (correction.total_score / correction.max_score) * 100
            
            const isSelected = selectedItems.includes(correction.id)
            
            return (
              <div
                key={correction.id}
                className={clsx(
                  "card p-6 transition-all animate-slide-up relative hover:shadow-xl cursor-pointer",
                  isSelected ? "border-primary-500 ring-2 ring-primary-500/50" : "hover:border-primary-500/50"
                )}
                style={{ animationDelay: `${index * 50}ms` }}
                onClick={(e) => {
                  // 点击卡片任意位置打开详情（除了特定按钮）
                  if (!isSelectionMode && !e.target.closest('button[data-action]')) {
                    setCurrentDetailId(correction.id)
                    setDetailDrawerOpen(true)
                  }
                }}
              >
                {/* 选择框（批量管理模式） */}
                {isSelectionMode && (
                  <div 
                    className="absolute top-4 left-4 z-20"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelection(correction.id)}
                      className="w-5 h-5 rounded border-2 border-slate-600 bg-slate-800 checked:bg-primary-500 checked:border-primary-500 cursor-pointer"
                    />
                  </div>
                )}

                {/* 学科标签徽章 */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <span className={`px-3 py-1 ${subjectInfo.bg} ${subjectInfo.color} rounded-full text-sm font-medium`}>
                      {subjectInfo.label}
                    </span>
                    {correction.grade && (
                      <span className="badge bg-slate-700 text-slate-300 text-xs">
                        {correction.grade}
                      </span>
                    )}
                  </div>
                  {correction.corrected_image_url && (
                    <span className="flex items-center gap-1 text-emerald-400 text-xs">
                      <CheckCircle2 className="w-3 h-3" />
                      已批改
                    </span>
                  )}
                </div>

                {/* 标题和时间 */}
                <div className="mb-4">
                  <h3 className="text-white font-semibold text-lg mb-1 line-clamp-1">
                    {correction.exam_title || '试卷批改'}
                  </h3>
                  <div className="flex items-center gap-2 text-slate-400 text-sm">
                    <Clock className="w-4 h-4" />
                    {new Date(correction.created_at).toLocaleString('zh-CN', {
                      month: 'numeric',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </div>
                </div>

                {/* 得分 */}
                <div className="mb-4">
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="text-3xl font-bold text-white">
                      {correction.total_score}
                    </span>
                    <span className="text-slate-400">/ {correction.max_score}</span>
                    <span className={clsx(
                      "ml-auto text-lg font-semibold",
                      scorePercent >= 60 ? "text-emerald-400" : "text-red-400"
                    )}>
                      {scorePercent.toFixed(0)}%
                    </span>
                  </div>
                  
                  {/* 进度条 */}
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={clsx(
                        "h-full transition-all duration-500",
                        scorePercent >= 60 
                          ? "bg-gradient-to-r from-emerald-500 to-green-500"
                          : "bg-gradient-to-r from-red-500 to-orange-500"
                      )}
                      style={{ width: `${Math.min(100, scorePercent)}%` }}
                    />
                  </div>
                </div>

                {/* 题目统计 */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                    <div className="text-slate-400 text-xs mb-1">总题数</div>
                    <div className="text-white font-bold">{correction.question_count}</div>
                  </div>
                  <div className="text-center p-3 bg-emerald-500/10 rounded-lg">
                    <div className="text-emerald-400 text-xs mb-1 flex items-center justify-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      答对
                    </div>
                    <div className="text-emerald-400 font-bold">{correction.correct_count}</div>
                  </div>
                  <div className="text-center p-3 bg-red-500/10 rounded-lg">
                    <div className="text-red-400 text-xs mb-1 flex items-center justify-center gap-1">
                      <XCircle className="w-3 h-3" />
                      答错
                    </div>
                    <div className="text-red-400 font-bold">{correction.wrong_count}</div>
                  </div>
                </div>

                {/* 薄弱点 */}
                {correction.weak_points && correction.weak_points.length > 0 && (
                  <div className="mb-4">
                    <div className="text-slate-400 text-xs mb-2">薄弱知识点:</div>
                    <div className="flex flex-wrap gap-2">
                      {correction.weak_points.slice(0, 3).map((point, i) => (
                        <span key={i} className="badge-warning text-xs">
                          {point}
                        </span>
                      ))}
                      {correction.weak_points.length > 3 && (
                        <span className="text-slate-500 text-xs">
                          +{correction.weak_points.length - 3}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* 操作按钮（仅在非选择模式显示） */}
                {!isSelectionMode && (
                  <div className="pt-4 border-t border-slate-800 flex items-center justify-between gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm('确定要删除这条批改记录吗？这将同时删除关联的错题记录。')) {
                          deleteMutation.mutate({ id: correction.id, subject: correction.subject })
                        }
                      }}
                      data-action="delete"
                      disabled={deleteMutation.isPending}
                      className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-all disabled:opacity-50"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    
                    <div className="flex items-center gap-2 text-primary-400 text-sm">
                      <span>点击查看详情</span>
                      <ArrowRight className="w-4 h-4" />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="card p-12 text-center">
          <FileCheck className="w-16 h-16 text-slate-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">
            {selectedSubject ? 
              `暂无${SUBJECTS.find(s => s.value === selectedSubject)?.label}批改记录` : 
              '暂无批改记录'
            }
          </h3>
          <p className="text-slate-400 mb-4">
            {selectedSubject ? (
              <span>
                该学科暂无批改记录，<button onClick={() => setSelectedSubject('')} className="text-primary-400 hover:text-primary-300 underline">查看全部</button>
              </span>
            ) : (
              '上传试卷让AI帮你批改吧！'
            )}
          </p>
          {!selectedSubject && (
            <button
              onClick={() => navigate('/exam-upload')}
              className="btn-primary inline-flex items-center gap-2"
            >
              <ImageIcon className="w-4 h-4" />
              上传试卷
            </button>
          )}
        </div>
      )}

      {/* 分页 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="btn-secondary px-4 py-2 disabled:opacity-50"
          >
            上一页
          </button>
          
          <div className="flex items-center gap-2">
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
          </div>
          
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="btn-secondary px-4 py-2 disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}

      {/* 图片查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />

      {/* 详情抽屉 */}
      <CorrectionDetailDrawer
        isOpen={detailDrawerOpen}
        onClose={() => setDetailDrawerOpen(false)}
        correctionId={currentDetailId}
        subject={corrections.find(c => c.id === currentDetailId)?.subject || 'chinese'}
        allIds={corrections.map(c => c.id)}
        onNavigate={(newId) => setCurrentDetailId(newId)}
      />
    </div>
  )
}

