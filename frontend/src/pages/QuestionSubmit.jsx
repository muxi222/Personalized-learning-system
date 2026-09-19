import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { questionApi, taskApi } from '../lib/api'
import { createTaskMonitor, loadTaskState } from '../lib/taskStream'
import {
  Send,
  Loader2,
  CheckCircle2,
  AlertCircle,
  BookOpen,
  ImagePlus,
  Upload,
  Camera,
  X,
  Maximize2
} from 'lucide-react'
import toast from 'react-hot-toast'
import ImageViewer from '../components/ImageViewer'

const MAX_ACTIVE_IMAGE_TASKS = 3
const PERSISTED_IMAGE_TASKS_KEY = 'questionSubmit:imageTasks'
const TASKSTREAM_ACTIVE_SET_KEY = 'task_active_ids'

// 10个学科 - 对应5个模块
const SUBJECTS = [
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
  { value: 'easy', label: '简单' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困难' },
]

export default function QuestionSubmit() {
  const navigate = useNavigate()
  // 默认展示“图片上传”
  const [inputMode, setInputMode] = useState('image') // 'text' or 'image'
  const [selectedFile, setSelectedFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [formData, setFormData] = useState({
    content: '',
    title: '',
    subject: 'math',
    difficulty: 'medium',
    student_answer: '',
    correct_answer: '',
    tags: '',
  })
  const [taskId, setTaskId] = useState(null)
  const [taskSubject, setTaskSubject] = useState(null)
  const [taskStatus, setTaskStatus] = useState(null)
  const [polling, setPolling] = useState(false)
  const [taskProgress, setTaskProgress] = useState(0)
  const [taskStep, setTaskStep] = useState('')
  const [taskError, setTaskError] = useState('')

  // 图片录入：支持同时多个任务（用于展示“正在上传/处理中”的所有题目，并限制并发<=3）
  const [imageTasks, setImageTasks] = useState([])
  const imageMonitorsRef = useRef(new Map())
  const hydratedImageTasksRef = useRef(false)
  const [selectedTaskIds, setSelectedTaskIds] = useState(() => new Set())

  const monitorRef = useRef(null)
  const lastToastStatusRef = useRef(null)
  const persistedTaskKey = 'questionSubmit:lastTask'

  const activeImageTaskCount = imageTasks.filter(t => t && (t.status === 'pending' || t.status === 'processing')).length
  const canStartMoreImageTasks = activeImageTaskCount < MAX_ACTIVE_IMAGE_TASKS

  const upsertImageTask = useCallback((taskId, patch) => {
    if (!taskId) return
    setImageTasks(prev => {
      const idx = prev.findIndex(t => t.taskId === taskId)
      if (idx === -1) return [{ taskId, ...patch }, ...prev]
      const next = [...prev]
      next[idx] = { ...next[idx], ...patch }
      return next
    })
  }, [])

  const removeImageTask = useCallback((taskId) => {
    if (!taskId) return
    setImageTasks(prev => prev.filter(t => t.taskId !== taskId))
    const mon = imageMonitorsRef.current.get(taskId)
    if (mon) {
      mon.stop()
      imageMonitorsRef.current.delete(taskId)
    }
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      next.delete(taskId)
      return next
    })
  }, [])

  const cleanupTaskLocalCache = useCallback((taskId) => {
    if (!taskId) return
    try {
      localStorage.removeItem(`task_state:${taskId}`)
    } catch {
      // ignore
    }
    try {
      const raw = localStorage.getItem(TASKSTREAM_ACTIVE_SET_KEY)
      const arr = raw ? JSON.parse(raw) : []
      if (Array.isArray(arr)) {
        const next = arr.filter((x) => x !== taskId)
        localStorage.setItem(TASKSTREAM_ACTIVE_SET_KEY, JSON.stringify(next))
      }
    } catch {
      // ignore
    }
  }, [])

  const toggleSelected = useCallback((taskId, checked) => {
    if (!taskId) return
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(taskId)
      else next.delete(taskId)
      return next
    })
  }, [])

  const bulkSelect = useCallback((taskIds, checked) => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      taskIds.forEach((id) => {
        if (checked) next.add(id)
        else next.delete(id)
      })
      return next
    })
  }, [])

  // Restore in-progress image tasks after refresh / revisit
  useEffect(() => {
    try {
      const fromPage = (() => {
        const raw = localStorage.getItem(PERSISTED_IMAGE_TASKS_KEY)
        if (!raw) return []
        const arr = JSON.parse(raw)
        return Array.isArray(arr) ? arr : []
      })()

      const fromTaskStream = (() => {
        const raw = localStorage.getItem(TASKSTREAM_ACTIVE_SET_KEY)
        if (!raw) return []
        const arr = JSON.parse(raw)
        // taskStream stores active ids (all tasks); we will filter to intake-image tasks by cached result below
        return Array.isArray(arr) ? arr.map((id) => ({ taskId: id })) : []
      })()

      const merged = [...fromPage, ...fromTaskStream]
      const seen = new Set()
      const metas = []
      for (const m of merged) {
        const id = m?.taskId
        if (!id || seen.has(id)) continue
        seen.add(id)
        metas.push(m)
      }

      if (metas.length === 0) {
        hydratedImageTasksRef.current = true
        return
      }

      // Hydrate from persisted task state snapshots, then resume monitors for active tasks
      metas.forEach((meta) => {
        const id = meta?.taskId
        if (!id) return
        const cached = loadTaskState(id)
        const inputType = cached?.result?.stages?.queued?.request?.input_type
        // Only restore intake OCR image tasks here (avoid polluting list with other task types)
        if (inputType && inputType !== 'image') return

        const inferredSubject = meta?.subject
          || cached?.result?.stages?.queued?.request?.subject
          || cached?.result?.stages?.queued?.request?.user_selected_subject
          || null

        upsertImageTask(id, {
          taskId: id,
          subject: inferredSubject,
          filename: meta?.filename,
          createdAt: meta?.createdAt || Date.now(),
          status: cached?.status,
          progress: cached?.progress,
          step: cached?.current_step,
          error: cached?.error_message,
          imageId: cached?.image_id,
        })
        if (cached?.status === 'pending' || cached?.status === 'processing') {
          // Resume monitor
          startImageTaskMonitor(id, inferredSubject)
        }
      })
    } catch {
      // ignore
    }
    hydratedImageTasksRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Persist task list metadata for refresh recovery (avoid large blobs; task state is persisted by taskStream.js)
  useEffect(() => {
    if (!hydratedImageTasksRef.current) return
    try {
      const compact = imageTasks.map(t => ({
        taskId: t.taskId,
        subject: t.subject,
        filename: t.filename,
        createdAt: t.createdAt,
      })).slice(0, 50)
      localStorage.setItem(PERSISTED_IMAGE_TASKS_KEY, JSON.stringify(compact))
    } catch {
      // ignore
    }
  }, [imageTasks])

  const startTaskMonitor = useCallback((id, subject) => {
    if (!id || !subject) return
    setTaskSubject(subject)

    // Persist so refresh/restart can auto-resume
    localStorage.setItem(persistedTaskKey, JSON.stringify({ taskId: id, subject }))

    // Stop previous monitor
    if (monitorRef.current) {
      monitorRef.current.stop()
      monitorRef.current = null
    }

    setPolling(true)
    monitorRef.current = createTaskMonitor({
      taskId: id,
      subject,
      onUpdate: (state) => {
        if (!state) return

        if (state.status) setTaskStatus(state.status)
        if (typeof state.progress === 'number') setTaskProgress(state.progress)
        if (state.current_step) setTaskStep(state.current_step)
        if (state.error_message) setTaskError(state.error_message)

        // Only toast on transitions
        if (state.status && state.status !== lastToastStatusRef.current) {
          lastToastStatusRef.current = state.status
          if (state.status === 'completed') toast.success('分析完成！')
          if (state.status === 'failed') toast.error(state.error_message || '处理失败')
        }

        if (state.status === 'completed') {
          setPolling(false)
          const saved = state?.result?.stages?.saved
          const qids = Array.isArray(saved?.question_ids) ? saved.question_ids : null
          const createdCount = typeof saved?.created_count === 'number' ? saved.created_count : (qids ? qids.length : null)
          const sourceImageId = saved?.source_image_id
          const imageId = state.image_id || sourceImageId

          // 图片录入：只要拿到 source_image_id（image_files.id），就统一跳转到“本图题目”页
          // 这页与“错题本 -> 查看本图题目”一致，方便用户按上传维度查看全部题目（即使只有 1 道）。
          if (imageId) {
            if (qids && qids.length) toast.success(`本次共识别 ${createdCount || qids.length} 道题`)
            setTimeout(() => navigate(`/questions/image/${imageId}`), 800)
          } else if (qids && qids.length) {
            // 兜底：没有 image_id 时，跳到第一道题详情
            setTimeout(() => navigate(`/questions/${qids[0]}?subject=${encodeURIComponent(subject)}`), 800)
          } else {
            setTimeout(() => navigate('/questions'), 800)
          }
        }

        if (state.status === 'failed') {
          setPolling(false)
          if (state.error_message) setTaskError(state.error_message)
        }
      },
      onTerminal: () => {
        // 任务结束后清理“自动恢复”指针，避免下次进入页面重复触发提示
        localStorage.removeItem(persistedTaskKey)
      },
    })
  }, [navigate])

  const startImageTaskMonitor = useCallback((id, subject) => {
    if (!id || !subject) return
    // Stop previous monitor for same task if any
    const existing = imageMonitorsRef.current.get(id)
    if (existing) existing.stop()

    imageMonitorsRef.current.set(id, createTaskMonitor({
      taskId: id,
      subject,
      onUpdate: (state) => {
        if (!state) return
        const saved = state?.result?.stages?.saved
        const qids = Array.isArray(saved?.question_ids) ? saved.question_ids : null
        const createdCount = typeof saved?.created_count === 'number'
          ? saved.created_count
          : (qids ? qids.length : null)
        const sourceImageId = saved?.source_image_id
        const imageId = state.image_id || sourceImageId

        upsertImageTask(id, {
          status: state.status || undefined,
          progress: typeof state.progress === 'number' ? state.progress : undefined,
          step: state.current_step || undefined,
          error: state.error_message || undefined,
          subject,
          imageId,
          questionIds: qids || undefined,
          createdCount,
        })
      },
      onTerminal: () => {
        const mon = imageMonitorsRef.current.get(id)
        if (mon) {
          mon.stop()
          imageMonitorsRef.current.delete(id)
        }
      },
    }))
  }, [upsertImageTask])

  // Auto-resume last task after refresh/restart
  useEffect(() => {
    const raw = localStorage.getItem(persistedTaskKey)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.taskId && parsed?.subject) {
        setTaskId(parsed.taskId)
        setTaskSubject(parsed.subject)
        const cached = loadTaskState(parsed.taskId)
        // 避免“进入页面立刻弹历史失败 toast”：把 lastToastStatus 预置为缓存状态
        if (cached?.status) lastToastStatusRef.current = cached.status
        if (cached?.status) setTaskStatus(cached.status)
        if (typeof cached?.progress === 'number') setTaskProgress(cached.progress)
        if (cached?.current_step) setTaskStep(cached.current_step)
        if (cached?.error_message) setTaskError(cached.error_message)
        // 仅在任务未结束时自动恢复监控；已 completed/failed 的历史任务不再自动启动
        if (cached?.status === 'completed' || cached?.status === 'failed') {
          localStorage.removeItem(persistedTaskKey)
        } else {
          startTaskMonitor(parsed.taskId, parsed.subject)
        }
      }
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (monitorRef.current) {
        monitorRef.current.stop()
        monitorRef.current = null
      }
      // Stop all image monitors
      for (const mon of imageMonitorsRef.current.values()) {
        try { mon.stop() } catch { /* ignore */ }
      }
      imageMonitorsRef.current.clear()
    }
  }, [])

  const submitMutation = useMutation({
    mutationFn: questionApi.create,
    onSuccess: (response) => {
      setTaskId(response.data.task_id)
      setTaskSubject(formData.subject)
      setTaskStatus('pending')
      startTaskMonitor(response.data.task_id, formData.subject)
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || '提交失败')
    },
  })

  const submitImageMutation = useMutation({
    mutationFn: async ({ file, subject, difficulty, title }) => {
      const formDataToSend = new FormData()
      formDataToSend.append('input_type', 'image')
      formDataToSend.append('file', file)
      formDataToSend.append('subject', subject)
      formDataToSend.append('difficulty', difficulty)
      if (title) {
        formDataToSend.append('title', title)
      }

      // 使用 questionApi，根据 subject 自动路由到对应模块
      const { createApiClient } = await import('../lib/api')
      const client = createApiClient(subject)
      
      return client.post('/questions/ocr', formDataToSend, {
        headers: {
          'Content-Type': 'multipart/form-data',
        }
      }).then(res => res.data)
    },
    onSuccess: (data, vars) => {
      const id = data?.task_id
      if (!id) {
        toast.error('上传成功但未返回task_id')
        return
      }
      upsertImageTask(id, {
        taskId: id,
        status: 'pending',
        progress: 0,
        step: '任务已提交，等待处理...',
        subject: vars?.subject,
        filename: vars?.file?.name,
        createdAt: Date.now(),
      })
      startImageTaskMonitor(id, vars?.subject)
      toast.success('图片已提交，AI正在识别分析...')
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || error.message || 'OCR识别失败')
    },
  })

  // 处理文件选择
  const handleFileSelect = useCallback((file) => {
    if (file && file.type.startsWith('image/')) {
      setSelectedFile(file)
      const url = URL.createObjectURL(file)
      setPreviewUrl(url)
      setTaskId(null)
      setTaskSubject(null)
      setTaskStatus(null)
      setPolling(false)
      setTaskProgress(0)
      setTaskStep('')
      setTaskError('')
      lastToastStatusRef.current = null
      if (monitorRef.current) {
        monitorRef.current.stop()
        monitorRef.current = null
      }
    } else {
      toast.error('请选择图片文件')
    }
  }, [])

  // 拖拽处理
  const handleDrop = useCallback((e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    handleFileSelect(file)
  }, [handleFileSelect])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
  }, [])

  // 文件输入处理
  const handleFileInput = useCallback((e) => {
    const file = e.target.files[0]
    handleFileSelect(file)
  }, [handleFileSelect])

  // 清除图片
  const clearImage = useCallback(() => {
    setSelectedFile(null)
    setPreviewUrl(null)
  }, [])

  const submitTextMutation = useMutation({
    mutationFn: async () => {
      // 构建文字数据（JSON格式）
      const textData = {
        content: formData.content,
        student_answer: formData.student_answer,
        correct_answer: formData.correct_answer,
        tags: formData.tags ? formData.tags.split(',').map(t => t.trim()) : [],
        knowledge_points: [],
        question_type: '',
      }

      const formDataToSend = new FormData()
      formDataToSend.append('input_type', 'text')
      formDataToSend.append('text_data', JSON.stringify(textData))
      formDataToSend.append('subject', formData.subject)
      formDataToSend.append('difficulty', formData.difficulty)
      if (formData.title) {
        formDataToSend.append('title', formData.title)
      }

      // 使用 questionApi，根据 subject 自动路由到对应模块
      const subject = formData.subject
      const { createApiClient } = await import('../lib/api')
      const client = createApiClient(subject)
      
      return client.post('/questions/ocr', formDataToSend, {
        headers: {
          'Content-Type': 'multipart/form-data',
        }
      }).then(res => res.data)
    },
    onSuccess: (data) => {
      setTaskId(data.task_id)
      setTaskSubject(formData.subject)
      setTaskStatus('pending')
      startTaskMonitor(data.task_id, formData.subject)
      toast.success('文字已提交，AI正在处理分析...')
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || error.message || '提交失败')
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()

    if (inputMode === 'text') {
      if (!formData.content.trim()) {
        toast.error('请输入题目内容')
        return
      }
      submitTextMutation.mutate()
    } else {
      if (!selectedFile) {
        toast.error('请上传题目图片')
        return
      }
      if (!canStartMoreImageTasks) {
        toast.error(`同时录入中的错题图片不能超过${MAX_ACTIVE_IMAGE_TASKS}张，请等待当前任务处理完成后再上传`)
        return
      }
      submitImageMutation.mutate({
        file: selectedFile,
        subject: formData.subject,
        difficulty: formData.difficulty,
        title: formData.title,
      })
      // 清空预览，允许继续上传下一张（在并发上限内）
      clearImage()
    }
  }

  const isProcessing = submitTextMutation.isPending || polling

  const cancelCurrentTask = useCallback(async () => {
    if (!taskId) return
    const subject = taskSubject || formData.subject
    try {
      await taskApi.cancel(taskId, subject)
    } catch (e) {
      // ignore; we'll stop UI waiting anyway
    }
    if (monitorRef.current) {
      monitorRef.current.stop()
      monitorRef.current = null
    }
    localStorage.removeItem(persistedTaskKey)
    setPolling(false)
    setTaskStatus('failed')
    setTaskProgress(100)
    setTaskStep('任务已取消')
    setTaskError('用户已取消任务')
    toast.success('已取消任务')
  }, [taskId, taskSubject, formData.subject])

  const cancelImageTask = useCallback(async (id, subject) => {
    if (!id) return
    try {
      await taskApi.cancel(id, subject)
    } catch (e) {
      // ignore; we'll stop UI waiting anyway
    }
    const mon = imageMonitorsRef.current.get(id)
    if (mon) {
      mon.stop()
      imageMonitorsRef.current.delete(id)
    }
    upsertImageTask(id, {
      status: 'failed',
      progress: 100,
      step: '任务已取消',
      error: '用户已取消任务',
    })
    toast.success('已取消任务')
  }, [upsertImageTask])

  const bulkDeleteTasks = useCallback(async (tasks) => {
    const selected = tasks.filter((t) => t && selectedTaskIds.has(t.taskId))
    if (selected.length === 0) return

    // For running tasks: cancel on backend first (best-effort). For completed/failed: backend may or may not support delete;
    // we still attempt cancel to clean server state, but UI will always remove locally.
    const toCancel = selected.filter(t => t.status === 'pending' || t.status === 'processing')
    if (toCancel.length) {
      await Promise.allSettled(toCancel.map((t) => taskApi.cancel(t.taskId, t.subject || formData.subject)))
    } else {
      // best-effort cleanup server task rows for non-running tasks too
      await Promise.allSettled(selected.map((t) => taskApi.cancel(t.taskId, t.subject || formData.subject)))
    }

    selected.forEach((t) => {
      cleanupTaskLocalCache(t.taskId)
      removeImageTask(t.taskId)
    })
    toast.success(`已删除 ${selected.length} 个任务`)
  }, [selectedTaskIds, cleanupTaskLocalCache, removeImageTask, formData.subject])

  return (
    <div className="max-w-3xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-display text-2xl font-bold text-slate-800 mb-2">
          录入错题
        </h1>
        <p className="text-slate-500">
          输入题目内容或上传图片，AI将自动分析错因并生成举一反三题目
        </p>
      </div>

      {/* 输入模式切换 */}
      <div className="card p-4 mb-6">
        <div className="flex gap-4">
          <button
            type="button"
            onClick={() => setInputMode('image')}
            className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
              inputMode === 'image'
                ? 'bg-primary-500 text-white'
                : 'bg-slate-50 text-slate-500 hover:bg-slate-50'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <ImagePlus className="w-5 h-5" />
              图片上传
            </div>
          </button>
          <button
            type="button"
            onClick={() => setInputMode('text')}
            className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
              inputMode === 'text'
                ? 'bg-primary-500 text-white'
                : 'bg-slate-50 text-slate-500 hover:bg-slate-50'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <BookOpen className="w-5 h-5" />
              文字输入
            </div>
          </button>
        </div>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="card p-6 space-y-5">
          {/* Subject and Difficulty */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-600 mb-2">
                学科 *
              </label>
              <select
                value={formData.subject}
                onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
                className="input"
              >
                {SUBJECTS.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 mb-2">
                难度
              </label>
              <select
                value={formData.difficulty}
                onChange={(e) => setFormData({ ...formData, difficulty: e.target.value })}
                className="input"
              >
                {DIFFICULTIES.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-2">
              题目标题
            </label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="input"
              placeholder="简短描述题目（可选）"
            />
          </div>

          {/* 图片上传模式 */}
          {inputMode === 'image' && (
            <div>
              <label className="block text-sm font-medium text-slate-600 mb-2">
                上传题目图片 *
              </label>
              {!previewUrl ? (
                <div
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                    canStartMoreImageTasks ? 'border-slate-200 hover:border-primary-500 cursor-pointer' : 'border-red-500/40 cursor-not-allowed opacity-70'
                  }`}
                >
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleFileInput}
                    className="hidden"
                    id="question-image-upload"
                    disabled={!canStartMoreImageTasks}
                  />
                  <label htmlFor="question-image-upload" className="cursor-pointer">
                    <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Upload className="w-8 h-8 text-slate-500" />
                    </div>
                    <p className="text-slate-800 font-medium mb-2">
                      {canStartMoreImageTasks ? '点击或拖拽上传题目图片' : `已达到同时上传上限（${MAX_ACTIVE_IMAGE_TASKS}张）`}
                    </p>
                    <p className="text-slate-500 text-sm">
                      支持 JPG、PNG、HEIC 格式，AI将自动识别题目内容
                    </p>
                  </label>

                  {/* 拍照按钮 */}
                  <div className="mt-6 pt-6 border-t border-slate-200">
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleFileInput}
                      className="hidden"
                      id="question-camera-capture"
                      disabled={!canStartMoreImageTasks}
                    />
                    <label
                      htmlFor="question-camera-capture"
                      className="btn-secondary inline-flex items-center gap-2 cursor-pointer"
                    >
                      <Camera className="w-5 h-5" />
                      拍照上传
                    </label>
                  </div>
                </div>
              ) : (
                <div className="relative group">
                  <img
                    src={previewUrl}
                    alt="题目预览"
                    className="w-full rounded-lg cursor-pointer transition-all group-hover:brightness-110"
                    onClick={() => setViewerOpen(true)}
                  />
                  <button
                    type="button"
                    onClick={clearImage}
                    className="absolute top-2 right-2 p-2 bg-white rounded-full hover:bg-slate-50 transition-colors z-10"
                  >
                    <X className="w-5 h-5 text-slate-800" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      setViewerOpen(true)
                    }}
                    className="absolute top-2 left-2 p-2 bg-white rounded-full hover:bg-slate-50 transition-colors opacity-0 group-hover:opacity-100"
                  >
                    <Maximize2 className="w-5 h-5 text-white" />
                  </button>
                </div>
              )}
              <p className="text-slate-500 text-sm mt-2">
                <strong>提示：</strong>OCR将自动识别题目、答案等信息，识别后可在题目详情页补充和修改
              </p>
            </div>
          )}

          {/* 文字输入模式 */}
          {inputMode === 'text' && (
            <>
              {/* Content */}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">
                  题目内容 *
                </label>
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                  className="textarea h-40"
                  placeholder="请输入完整的题目内容..."
                  required
                />
              </div>

              {/* Student Answer */}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">
                  你的答案
                </label>
                <textarea
                  value={formData.student_answer}
                  onChange={(e) => setFormData({ ...formData, student_answer: e.target.value })}
                  className="textarea h-24"
                  placeholder="你做题时写的答案（便于分析错误原因）"
                />
              </div>

              {/* Correct Answer */}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">
                  正确答案
                </label>
                <textarea
                  value={formData.correct_answer}
                  onChange={(e) => setFormData({ ...formData, correct_answer: e.target.value })}
                  className="textarea h-24"
                  placeholder="题目的正确答案（如果知道的话）"
                />
              </div>

              {/* Tags */}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">
                  标签
                </label>
                <input
                  type="text"
                  value={formData.tags}
                  onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                  className="input"
                  placeholder="用逗号分隔，如：导数, 极值, 函数"
                />
              </div>
            </>
          )}
        </div>

        {/* Status indicator */}
        {inputMode === 'text' && taskStatus && (
          <div className={`card p-4 ${
            taskStatus === 'completed' ? 'bg-emerald-500/10 border-emerald-500/30' :
            taskStatus === 'failed' ? 'bg-red-500/10 border-red-500/30' :
            'bg-primary-500/10 border-primary-500/30'
          }`}>
            <div className="flex items-start gap-3">
              {taskStatus === 'completed' ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-600" />
              ) : taskStatus === 'failed' ? (
                <AlertCircle className="w-5 h-5 text-red-600" />
              ) : (
                <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-slate-800 font-medium">
                  {taskStatus === 'completed' ? '分析完成！即将跳转...' :
                   taskStatus === 'failed' ? '处理失败' :
                   taskStatus === 'processing' ? inputMode === 'image' ? 'AI正在识别和分析...' : 'AI正在分析中...' :
                   '任务已提交，等待处理...'}
                </p>
                {(taskStep || typeof taskProgress === 'number') && taskStatus !== 'failed' && (
                  <p className="text-sm text-slate-600 mt-1">
                    {taskSubject ? `学科：${(SUBJECTS.find(s => s.value === taskSubject)?.label || taskSubject)}，` : ''}
                    {taskStep ? `${taskStep}` : '处理中...'}
                    {typeof taskProgress === 'number' ? `（${Math.round(taskProgress)}%）` : ''}
                  </p>
                )}
                {taskStatus === 'failed' && taskError && (
                  <p className="text-sm text-red-600 mt-1 break-words">
                    {taskError}
                  </p>
                )}
              </div>
              {(taskStatus === 'pending' || taskStatus === 'processing') && (
                <button
                  type="button"
                  onClick={cancelCurrentTask}
                  className="p-1.5 rounded-md hover:bg-slate-50 text-slate-600 hover:text-slate-800 transition-colors"
                  title="取消任务"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        )}

        {/* Image intake tasks list */}
        {inputMode === 'image' && imageTasks.length > 0 && (
          <div className="card p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="text-slate-800 font-medium">
                正在录入 / 处理中（{activeImageTaskCount}/{MAX_ACTIVE_IMAGE_TASKS}）
              </div>
              {!canStartMoreImageTasks && (
                <div className="text-xs text-red-600">
                  已达到并发上限，请等待完成后再上传
                </div>
              )}
            </div>
            {(() => {
              const inProgress = imageTasks.filter(t => t && (t.status === 'pending' || t.status === 'processing'))
              const completed = imageTasks.filter(t => t && t.status === 'completed')
              const failed = imageTasks.filter(t => t && t.status === 'failed')

              const Section = ({ title, tasks, tone }) => {
                const ids = tasks.map(t => t.taskId)
                const selectedCount = ids.filter((id) => selectedTaskIds.has(id)).length
                const allSelected = ids.length > 0 && selectedCount === ids.length

                return (
                  <div className="mb-4 last:mb-0">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <div className="text-slate-800 font-medium">
                        {title}（{tasks.length}）
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-600 flex items-center gap-2">
                          <input
                            type="checkbox"
                            className="accent-primary-500"
                            checked={allSelected}
                            onChange={(e) => bulkSelect(ids, e.target.checked)}
                          />
                          全选
                        </label>
                        <button
                          type="button"
                          className="btn-secondary text-sm px-3 py-1.5"
                          disabled={selectedCount === 0}
                          onClick={() => bulkDeleteTasks(tasks)}
                        >
                          批量删除{selectedCount ? `（${selectedCount}）` : ''}
                        </button>
                      </div>
                    </div>

                    {tasks.length === 0 ? (
                      <div className="text-sm text-slate-500">暂无</div>
                    ) : (
                      <div className="space-y-2">
                        {tasks.map(t => (
                          <div key={t.taskId} className={`flex items-start gap-3 rounded-lg border bg-white p-3 ${
                            tone === 'ok' ? 'border-emerald-500/25' : tone === 'bad' ? 'border-red-500/25' : 'border-slate-200'
                          }`}>
                            <div className="mt-1">
                              <input
                                type="checkbox"
                                className="accent-primary-500"
                                checked={selectedTaskIds.has(t.taskId)}
                                onChange={(e) => toggleSelected(t.taskId, e.target.checked)}
                              />
                            </div>
                            <div className="mt-0.5">
                              {t.status === 'completed' ? (
                                <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                              ) : t.status === 'failed' ? (
                                <AlertCircle className="w-5 h-5 text-red-600" />
                              ) : (
                                <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-2">
                                <div className="text-slate-800 font-medium truncate">
                                  {t.filename || '图片录入任务'}
                                </div>
                                <div className="text-xs text-slate-500 shrink-0">
                                  {t.subject ? (SUBJECTS.find(s => s.value === t.subject)?.label || t.subject) : ''}
                                </div>
                              </div>
                              <div className="text-sm text-slate-600 mt-1">
                                {t.status === 'completed' ? '已完成' :
                                 t.status === 'failed' ? '失败' :
                                 t.status === 'processing' ? '处理中...' :
                                 '等待处理...'}
                                {t.step ? ` · ${t.step}` : ''}
                                {typeof t.progress === 'number' ? `（${Math.round(t.progress)}%）` : ''}
                              </div>
                              {t.status === 'failed' && t.error && (
                                <div className="text-sm text-red-600 mt-1 break-words">
                                  {t.error}
                                </div>
                              )}

                              <div className="mt-2 flex items-center gap-2 flex-wrap">
                                {t.imageId && (
                                  <button
                                    type="button"
                                    className="btn-secondary text-sm px-3 py-1.5"
                                    onClick={() => navigate(`/questions/image/${t.imageId}`)}
                                  >
                                    查看本图题目
                                  </button>
                                )}
                                <button
                                  type="button"
                                  className="btn-secondary text-sm px-3 py-1.5"
                                  onClick={() => navigate(`/tasks/${t.taskId}?subject=${encodeURIComponent(t.subject || '')}`)}
                                >
                                  任务详情
                                </button>
                                {typeof t.createdCount === 'number' && t.status === 'completed' && (
                                  <span className="text-xs text-slate-500">
                                    识别 {t.createdCount} 道
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {(t.status === 'pending' || t.status === 'processing') && (
                                <button
                                  type="button"
                                  onClick={() => cancelImageTask(t.taskId, t.subject || formData.subject)}
                                  className="p-1.5 rounded-md hover:bg-slate-50 text-slate-600 hover:text-slate-800 transition-colors"
                                  title="取消任务"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              )}
                              {(t.status === 'completed' || t.status === 'failed') && (
                                <button
                                  type="button"
                                  onClick={() => { cleanupTaskLocalCache(t.taskId); removeImageTask(t.taskId) }}
                                  className="p-1.5 rounded-md hover:bg-slate-50 text-slate-600 hover:text-slate-800 transition-colors"
                                  title="移除"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              }

              return (
                <div>
                  <Section title="进行中" tasks={inProgress} tone="progress" />
                  <Section title="成功" tasks={completed} tone="ok" />
                  <Section title="失败" tasks={failed} tone="bad" />
                </div>
              )
            })()}
          </div>
        )}

        {/* Submit button */}
        <button
          type="submit"
          disabled={
            inputMode === 'text'
              ? isProcessing
              : (submitImageMutation.isPending || !selectedFile || !canStartMoreImageTasks)
          }
          className="btn-primary w-full flex items-center justify-center gap-2 text-lg py-4"
        >
          {(inputMode === 'text' ? isProcessing : submitImageMutation.isPending) ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              {inputMode === 'image' ? 'OCR识别中...' : '处理中...'}
            </>
          ) : (
            <>
              <Send className="w-5 h-5" />
              {inputMode === 'image' ? '上传并识别' : '提交分析'}
            </>
          )}
        </button>
      </form>

      {/* 图片查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={previewUrl}
        title="题目图片预览"
      />
    </div>
  )
}
