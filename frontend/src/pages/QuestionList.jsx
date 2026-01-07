import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi } from '../lib/api'
import {
  Search,
  Filter,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  Image as ImageIcon,
  Maximize2,
  Trash2
} from 'lucide-react'
import clsx from 'clsx'
import ImageViewer from '../components/ImageViewer'
import toast from 'react-hot-toast'

// 10个学科 + 全部选项
const SUBJECTS = [
  { value: '', label: '全部学科' },  // 空字符串表示查询所有模块
  // RPJ模块
  { value: 'chinese', label: '语文' },
  { value: 'english', label: '英语' },
  { value: 'politics', label: '政治' },
  // XMX模块
  { value: 'economics', label: '经济学' },
  // WZY模块
  { value: 'math', label: '数学' },
  { value: 'physics', label: '物理' },
  // WZM模块
  { value: 'chemistry', label: '化学' },
  // TONY模块
  { value: 'history', label: '历史' },
  { value: 'geography', label: '地理' },
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
  const [dateRange, setDateRange] = useState({ start: '', end: '' }) // YYYY-MM-DD
  const [groupBy, setGroupBy] = useState('upload') // upload | chapter
  const [chapterFilter, setChapterFilter] = useState('')
  const [knowledgePointFilter, setKnowledgePointFilter] = useState('')
  const [prevGroupBy, setPrevGroupBy] = useState('upload')
  const queryClient = useQueryClient()
  const [isSelectionMode, setIsSelectionMode] = useState(false)
  const [selectedItems, setSelectedItems] = useState([])
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const pageSize = 10

  const { data, isLoading } = useQuery({
    queryKey: ['questions', { page, page_size: pageSize, ...filters, group_by: groupBy, chapter: chapterFilter, knowledge_point: knowledgePointFilter, start_date: dateRange.start, end_date: dateRange.end }],
    queryFn: () => questionApi.list({
      page,
      page_size: pageSize,
      ...filters,
      group_by: groupBy,
      chapter: chapterFilter || undefined,
      knowledge_point: knowledgePointFilter || undefined,
      start_date: dateRange.start ? `${dateRange.start}T00:00:00` : undefined,
      end_date: dateRange.end ? `${dateRange.end}T23:59:59` : undefined,
    }),
    keepPreviousData: true,
  })

  // 题目类型下拉选项（按学科统计）
  const chaptersQuery = useQuery({
    queryKey: ['question-chapters', { subject: filters.subject, difficulty: filters.difficulty, search: filters.search }],
    enabled: groupBy === 'chapter' && !!filters.subject,
    queryFn: () => questionApi.getChapters({
      subject: filters.subject,
      difficulty: filters.difficulty || undefined,
      search: filters.search || undefined,
    }),
  })

  // 知识点下拉选项（按学科统计）
  const knowledgePointsQuery = useQuery({
    queryKey: ['question-knowledge-points', { subject: filters.subject, difficulty: filters.difficulty, search: filters.search }],
    enabled: !!filters.subject,
    queryFn: () => questionApi.getKnowledgePoints({
      subject: filters.subject,
      difficulty: filters.difficulty || undefined,
      search: filters.search || undefined,
    }),
  })

  const payload = data?.data || {}
  const isGrouped = payload?.items?.[0]?.questions
  const groups = isGrouped ? (payload.items || []) : []
  const questions = !isGrouped ? (payload.items || []) : []
  const totalQuestions = (payload?.total_questions ?? payload?.total) || 0
  const totalGroups = (payload?.total_groups ?? payload?.total) || 0
  const total = totalQuestions
  const totalPages = Math.ceil((isGrouped ? totalGroups : totalQuestions) / pageSize)

  const batchDeleteMutation = useMutation({
    mutationFn: (ids) => questionApi.batchDelete(ids),
    onSuccess: (resp) => {
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      const { deleted_count, failed_count } = resp?.data || {}
      if (!failed_count) {
        toast.success(`已成功删除 ${deleted_count || selectedItems.length} 道错题`)
      } else {
        toast.success(`已删除 ${deleted_count || 0} 道错题，${failed_count} 道删除失败`)
      }
      setSelectedItems([])
      setIsSelectionMode(false)
    },
    onError: () => {
      toast.error('批量删除失败')
    },
  })

  const toggleSelection = (id) => {
    setSelectedItems(prev =>
      prev.includes(id)
        ? prev.filter(item => item !== id)
        : [...prev, id]
    )
  }

  const toggleSelectAll = () => {
    if (selectedItems.length === questions.length) {
      setSelectedItems([])
    } else {
      setSelectedItems(questions.map(q => q.id))
    }
  }

  const handleBatchDelete = async () => {
    if (selectedItems.length === 0) {
      toast.error('请先选择要删除的错题')
      return
    }
    if (!confirm(`确定要删除 ${selectedItems.length} 道错题吗？`)) {
      return
    }
    batchDeleteMutation.mutate(selectedItems)
  }

  const handleDeleteChapter = async () => {
    if (!filters.subject) {
      toast.error('请先选择学科')
      return
    }
    if (!chapterFilter) {
      toast.error('请先选择题目类型')
      return
    }
    if (!confirm(`确定要删除【${chapterFilter}】分类下的所有错题吗？`)) {
      return
    }
    try {
      const resp = await questionApi.batchDeleteByChapter({
        subject: filters.subject,
        chapter: chapterFilter,
        difficulty: filters.difficulty || undefined,
        search: filters.search || undefined,
      })
      const { deleted_count, failed_count } = resp?.data || {}
      if (!failed_count) {
        toast.success(`已成功删除 ${deleted_count || 0} 道错题`)
      } else {
        toast.success(`已删除 ${deleted_count || 0} 道错题，${failed_count} 道删除失败`)
      }
      queryClient.invalidateQueries({ queryKey: ['questions'] })
    } catch (e) {
      toast.error('按分类删除失败')
    }
  }

  const handleDeleteFiltered = async () => {
    const hasAnyFilter = !!(
      filters.subject ||
      filters.difficulty ||
      filters.search ||
      (groupBy === 'chapter' && chapterFilter) ||
      (groupBy === 'knowledge_point' && knowledgePointFilter)
    )

    if (!hasAnyFilter) {
      toast.error('请先选择筛选条件后再删除')
      return
    }

    const estimated = isGrouped ? (payload?.total_questions ?? 0) : (payload?.total ?? 0)
    const hint = Number.isFinite(Number(estimated)) ? `约 ${estimated} 道` : ''

    if (!confirm(`确定要删除当前筛选结果${hint ? `（${hint}）` : ''}吗？此操作不可恢复。`)) {
      return
    }

    try {
      const resp = await questionApi.batchDeleteByFilter({
        subject: filters.subject || undefined,
        difficulty: filters.difficulty || undefined,
        search: filters.search || undefined,
        chapter: groupBy === 'chapter' ? (chapterFilter || undefined) : undefined,
        knowledge_point: groupBy === 'knowledge_point' ? (knowledgePointFilter || undefined) : undefined,
      })
      const { deleted_count, failed_count } = resp?.data || {}
      if (!failed_count) {
        toast.success(`已成功删除 ${deleted_count || 0} 道错题`)
      } else {
        toast.success(`已删除 ${deleted_count || 0} 道错题，${failed_count} 道删除失败`)
      }
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['question-chapters'] })
      queryClient.invalidateQueries({ queryKey: ['question-knowledge-points'] })
      setSelectedItems([])
      setIsSelectionMode(false)
    } catch (e) {
      toast.error('删除筛选结果失败')
    }
  }

  const extractImageIdFromUrl = (url) => {
    if (!url || typeof url !== 'string') return null
    const m = url.match(/\/image-files\/(\d+)\/content/)
    if (!m) return null
    const id = parseInt(m[1], 10)
    return Number.isFinite(id) ? id : null
  }

  const sortGroupQuestions = (qs) => {
    const arr = Array.isArray(qs) ? qs : []
    // Keep original order as fallback, but prefer explicit ordering fields when present.
    return arr
      .map((q, idx) => ({ q, __idx: idx }))
      .sort((a, b) => {
        const av = a?.q || {}
        const bv = b?.q || {}
        const ai = Number.isFinite(Number(av.upload_index)) ? Number(av.upload_index) : null
        const bi = Number.isFinite(Number(bv.upload_index)) ? Number(bv.upload_index) : null
        if (ai != null && bi != null && ai !== bi) return ai - bi
        if (ai != null && bi == null) return -1
        if (ai == null && bi != null) return 1

        const an = Number.isFinite(Number(av.question_number)) ? Number(av.question_number) : null
        const bn = Number.isFinite(Number(bv.question_number)) ? Number(bv.question_number) : null
        if (an != null && bn != null && an !== bn) return an - bn
        if (an != null && bn == null) return -1
        if (an == null && bn != null) return 1

        // stable fallback: keep backend order
        return a.__idx - b.__idx
      })
      .map(x => x.q)
  }

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
              const next = e.target.value
              setFilters({ ...filters, subject: next })
              setKnowledgePointFilter('')
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

          {/* Date range */}
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">日期</span>
            <input
              type="date"
              value={dateRange.start}
              onChange={(e) => {
                setDateRange(prev => ({ ...prev, start: e.target.value }))
                setPage(1)
              }}
              className="input w-auto"
            />
            <span className="text-slate-500 text-sm">-</span>
            <input
              type="date"
              value={dateRange.end}
              onChange={(e) => {
                setDateRange(prev => ({ ...prev, end: e.target.value }))
                setPage(1)
              }}
              className="input w-auto"
            />
          </div>

          {/* Group mode */}
          <select
            value={groupBy}
            onChange={(e) => {
              setGroupBy(e.target.value)
              setChapterFilter('')
              setKnowledgePointFilter('')
              setPage(1)
            }}
            className="input w-auto"
          >
            <option value="upload">按上传图片/文本</option>
            <option value="knowledge_point">按知识点分类</option>
            <option value="chapter">按题目类型(章节)</option>
            <option value="none">平铺列表</option>
          </select>

          {/* 知识点筛选（按知识点分类） */}
          {groupBy === 'knowledge_point' && (
            <select
              value={knowledgePointFilter}
              onChange={(e) => {
                setKnowledgePointFilter(e.target.value)
                setPage(1)
              }}
              className="input w-56"
              disabled={!filters.subject || knowledgePointsQuery.isLoading}
            >
              <option value="">
                {filters.subject ? '全部知识点' : '请先选择学科'}
              </option>
              {(knowledgePointsQuery.data?.data?.items || [])
                .filter(it => it.subject === filters.subject)
                .flatMap(it => it.knowledge_points || [])
                .map((c) => (
                  <option key={c.knowledge_point} value={c.knowledge_point}>
                    {c.knowledge_point} ({c.count})
                  </option>
                ))}
            </select>
          )}

          {/* Chapter filter (only for chapter grouping) */}
          {groupBy === 'chapter' && (
            <>
              <select
                value={chapterFilter}
                onChange={(e) => {
                  setChapterFilter(e.target.value)
                  setPage(1)
                }}
                className="input w-56"
                disabled={!filters.subject || chaptersQuery.isLoading}
              >
                <option value="">
                  {filters.subject ? '全部题目类型' : '请先选择学科'}
                </option>
                {(chaptersQuery.data?.data?.items || [])
                  .filter(it => it.subject === filters.subject)
                  .flatMap(it => it.chapters || [])
                  .map((c) => (
                    <option key={c.chapter} value={c.chapter}>
                      {c.chapter} ({c.count})
                    </option>
                  ))}
              </select>

              {chapterFilter && !isSelectionMode && (
                <button
                  type="button"
                  onClick={handleDeleteChapter}
                  className="bg-red-500/20 hover:bg-red-500/30 text-red-400 px-3 py-2 rounded-lg text-sm font-medium transition-all"
                >
                  <Trash2 className="w-4 h-4 inline mr-1" />
                  删除该分类
                </button>
              )}
            </>
          )}

          <button type="submit" className="btn-secondary flex items-center gap-2">
            <Filter className="w-4 h-4" />
            筛选
          </button>

          <div className="flex-1" />

          {/* 批量操作按钮 */}
          {isSelectionMode ? (
            <>
              <button
                type="button"
                onClick={toggleSelectAll}
                className="btn-secondary px-3 py-2 text-sm"
              >
                {selectedItems.length === questions.length ? '取消全选' : '全选'}
              </button>
              <button
                type="button"
                onClick={handleBatchDelete}
                disabled={selectedItems.length === 0 || batchDeleteMutation.isPending}
                className="bg-red-500/20 hover:bg-red-500/30 text-red-400 px-3 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4 inline mr-1" />
                {batchDeleteMutation.isPending ? '删除中...' : `删除 (${selectedItems.length})`}
              </button>
              <button
                type="button"
                onClick={handleDeleteFiltered}
                className="bg-red-500/10 hover:bg-red-500/20 text-red-300 px-3 py-2 rounded-lg text-sm font-medium transition-all"
              >
                删除筛选结果
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsSelectionMode(false)
                  setSelectedItems([])
                  // 退出批量管理时恢复之前的分组方式
                  setGroupBy(prevGroupBy)
                }}
                className="btn-secondary px-3 py-2 text-sm"
              >
                取消
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => {
                // 批量删除按“平铺列表”更直观，进入批量管理时强制切换为 none
                setPrevGroupBy(groupBy)
                setGroupBy('none')
                setChapterFilter('')
                setKnowledgePointFilter('')
                setIsSelectionMode(true)
              }}
              className="btn-secondary px-3 py-2 text-sm flex items-center gap-1"
            >
              <Trash2 className="w-4 h-4" />
              批量管理
            </button>
          )}
          {!isSelectionMode && (
            <button
              type="button"
              onClick={handleDeleteFiltered}
              className="bg-red-500/10 hover:bg-red-500/20 text-red-300 px-3 py-2 rounded-lg text-sm font-medium transition-all"
            >
              <Trash2 className="w-4 h-4 inline mr-1" />
              删除筛选结果
            </button>
          )}
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
      ) : (isGrouped ? groups.length > 0 : questions.length > 0) ? (
        <div className="space-y-4">
          {isGrouped ? (
            groups.map((group, index) => (
              <div
                key={group.group_key}
                className="card p-6 animate-slide-up"
                style={{ animationDelay: `${index * 50}ms` }}
              >
                {(() => {
                  const fromQuestions = (group.questions || []).find(q => q?.source_image_id)?.source_image_id
                  const fromPreview = extractImageIdFromUrl(group.preview_image_url)
                  const imageId = fromQuestions || fromPreview
                  const canGoImageGroup = groupBy === 'upload' && group.upload_type === 'image' && !!imageId
                  return (
                    <div className="flex items-start gap-4">
                      {/* 组预览图 */}
                      {group.preview_image_url && (
                        <div className="relative flex-shrink-0 w-32 h-32 rounded-xl overflow-hidden bg-slate-800/50 border border-slate-700/50 hover:border-primary-500/50 transition-all group">
                          <div
                            className="w-full h-full cursor-pointer"
                            onClick={(e) => {
                              e.preventDefault()
                              setViewerImage({
                                url: group.preview_image_url,
                                title: '上传图片'
                              })
                              setViewerOpen(true)
                            }}
                          >
                            <img
                              src={group.preview_image_url}
                              alt="上传图片"
                              className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300"
                            />
                            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                              <Maximize2 className="w-6 h-6 text-white" />
                            </div>
                          </div>

                          {/* 快捷入口：本图题目 */}
                          {canGoImageGroup && (
                            <Link
                              to={`/questions/image/${imageId}`}
                              onClick={(e) => e.stopPropagation()}
                              className="absolute bottom-2 left-2 px-2 py-1 rounded-md bg-primary-500/80 hover:bg-primary-500 text-white text-xs font-medium transition-all"
                              title="查看本次上传图片中的全部题目"
                            >
                              本图题目
                            </Link>
                          )}
                        </div>
                      )}

                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-4 mb-3">
                          <div className="min-w-0">
                            <h3 className="text-lg font-medium text-white line-clamp-1">
                              {groupBy === 'chapter'
                                ? `${SUBJECTS.find(s => s.value === group.subject)?.label || group.subject} · ${group.chapter || '未分类'}`
                                : groupBy === 'knowledge_point'
                                ? `${SUBJECTS.find(s => s.value === group.subject)?.label || group.subject} · ${group.knowledge_point || '未分类'}`
                                : `${SUBJECTS.find(s => s.value === group.subject)?.label || group.subject} · ${group.upload_type === 'image' ? '图片上传' : '文字录入'}`
                              }
                            </h3>
                            <p className="text-slate-400 text-sm mt-1">
                              共 {group.count} 道题
                            </p>
                            {(group.created_at || group.tags?.length) && (
                              <div className="flex flex-wrap items-center gap-2 mt-2">
                                {group.created_at && (
                                  <span className="text-slate-500 text-xs">
                                    {new Date(group.created_at).toLocaleString('zh-CN', { hour12: false })}
                                  </span>
                                )}
                                {(group.tags || []).slice(0, 6).map((t) => (
                                  <span key={t} className="badge-accent text-xs">
                                    {t}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>

                          {canGoImageGroup && (
                            <Link
                              to={`/questions/image/${imageId}`}
                              className="btn-secondary px-3 py-2 text-sm whitespace-nowrap"
                            >
                              查看本图题目
                            </Link>
                          )}
                        </div>

                        <div className="space-y-2">
                          {sortGroupQuestions(group.questions || []).map((q, qi) => (
                            <Link
                              key={q.id}
                              to={`/questions/${q.id}${q.subject ? `?subject=${encodeURIComponent(q.subject)}` : ''}`}
                              className="block rounded-lg bg-slate-800/40 hover:bg-slate-800/60 border border-slate-700/40 hover:border-primary-500/40 transition-all p-3"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-primary-500/15 text-primary-200 text-xs font-semibold flex-shrink-0">
                                      {qi + 1}
                                    </span>
                                    <div className="text-white text-sm font-medium line-clamp-1">
                                      {q.title || (q.content ? q.content.slice(0, 60) : '题目内容')}
                                    </div>
                                  </div>
                                  <div className="text-slate-400 text-xs line-clamp-1 mt-1">
                                    {q.content}
                                  </div>
                                </div>
                                <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0 mt-0.5" />
                              </div>
                            </Link>
                          ))}
                        </div>
                      </div>
                    </div>
                  )
                })()}
              </div>
            ))
          ) : (
            questions.map((question, index) => (
              <div
                key={question.id}
                className="card p-6 animate-slide-up"
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <div className="flex items-start gap-4">
                  {/* 选择框（批量管理模式） */}
                  {isSelectionMode && (
                    <input
                      type="checkbox"
                      className="mt-2 w-5 h-5 accent-primary-500"
                      checked={selectedItems.includes(question.id)}
                      onChange={() => toggleSelection(question.id)}
                    />
                  )}
                  {/* 图片缩略图 */}
                  {question.image_urls && question.image_urls.length > 0 && (
                    <div
                      className="flex-shrink-0 w-32 h-32 rounded-xl overflow-hidden bg-slate-800/50 border border-slate-700/50 cursor-pointer hover:border-primary-500/50 transition-all group relative"
                      onClick={(e) => {
                        e.preventDefault()
                        setViewerImage({
                          url: question.image_urls[0].startsWith('http') ? question.image_urls[0] : `/api/v1${question.image_urls[0]}`,
                          title: question.title || '题目图片'
                        })
                        setViewerOpen(true)
                      }}
                    >
                      <img
                        src={question.image_urls[0].startsWith('http') ? question.image_urls[0] : `/api/v1${question.image_urls[0]}`}
                        alt="题目图片"
                        className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300"
                      />
                      {question.source_image_id && (
                        <Link
                          to={`/questions/image/${question.source_image_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="absolute bottom-2 left-2 px-2 py-1 bg-black/70 rounded-md text-white text-xs font-medium backdrop-blur-sm hover:bg-black/80"
                        >
                          本图题目
                        </Link>
                      )}
                      {question.image_urls.length > 1 && (
                        <div className="absolute top-2 right-2 px-2 py-1 bg-black/70 rounded-full text-white text-xs font-medium backdrop-blur-sm">
                          +{question.image_urls.length - 1}
                        </div>
                      )}
                      <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                        <Maximize2 className="w-6 h-6 text-white" />
                      </div>
                    </div>
                  )}

                  {/* 题目内容 */}
                  <Link
                    to={`/questions/${question.id}${question.subject ? `?subject=${encodeURIComponent(question.subject)}` : ''}`}
                    className="flex-1 min-w-0 hover:opacity-80 transition-opacity"
                  >
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <h3 className="text-lg font-medium text-white line-clamp-1">
                        {question.title || question.content.slice(0, 80)}
                      </h3>
                      <ArrowRight className="w-5 h-5 text-slate-500 flex-shrink-0" />
                    </div>
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
                        {new Date(question.created_at).toLocaleString('zh-CN', { hour12: false })}
                      </span>
                    </div>
                  </Link>
                </div>
              </div>
            ))
          )}
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
