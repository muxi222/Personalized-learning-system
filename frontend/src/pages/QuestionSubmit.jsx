import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { questionApi, taskApi } from '../lib/api'
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
  const [inputMode, setInputMode] = useState('text') // 'text' or 'image'
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
  const [taskStatus, setTaskStatus] = useState(null)
  const [polling, setPolling] = useState(false)

  const submitMutation = useMutation({
    mutationFn: questionApi.create,
    onSuccess: (response) => {
      setTaskId(response.data.task_id)
      setTaskStatus('pending')
      pollTaskStatus(response.data.task_id)
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || '提交失败')
    },
  })

  const submitImageMutation = useMutation({
    mutationFn: async () => {
      const formDataToSend = new FormData()
      formDataToSend.append('file', selectedFile)
      formDataToSend.append('subject', formData.subject)
      formDataToSend.append('difficulty', formData.difficulty)
      if (formData.title) {
        formDataToSend.append('title', formData.title)
      }

      // 从 auth-storage 正确获取 token
      const authStorage = localStorage.getItem('auth-storage')
      let token = null
      if (authStorage) {
        const { state } = JSON.parse(authStorage)
        token = state?.token
      }

      const response = await fetch('/api/v1/questions/ocr', {
        method: 'POST',
        body: formDataToSend,
        headers: token ? {
          'Authorization': `Bearer ${token}`
        } : {}
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'OCR识别失败')
      }

      return response.json()
    },
    onSuccess: (data) => {
      setTaskId(data.task_id)
      setTaskStatus('pending')
      pollTaskStatus(data.task_id)
      toast.success('图片已上传，AI正在识别分析...')
    },
    onError: (error) => {
      toast.error(error.message || 'OCR识别失败')
    },
  })

  const pollTaskStatus = async (id) => {
    setPolling(true)
    const maxAttempts = 60 // 2 minutes max
    let attempts = 0

    const poll = async () => {
      try {
        const response = await taskApi.getStatus(id)
        const status = response.data.status

        setTaskStatus(status)

        if (status === 'completed') {
          setPolling(false)
          toast.success('分析完成！')
          if (response.data.result_id) {
            setTimeout(() => {
              navigate(`/questions/${response.data.result_id}`)
            }, 1500)
          }
          return
        }

        if (status === 'failed') {
          setPolling(false)
          toast.error(response.data.error_message || '处理失败')
          return
        }

        attempts++
        if (attempts < maxAttempts) {
          setTimeout(poll, 2000)
        } else {
          setPolling(false)
          toast.error('处理超时，请稍后查看结果')
        }
      } catch (error) {
        setPolling(false)
        toast.error('查询状态失败')
      }
    }

    poll()
  }

  // 处理文件选择
  const handleFileSelect = useCallback((file) => {
    if (file && file.type.startsWith('image/')) {
      setSelectedFile(file)
      const url = URL.createObjectURL(file)
      setPreviewUrl(url)
      setTaskId(null)
      setTaskStatus(null)
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

  const handleSubmit = (e) => {
    e.preventDefault()
    
    if (inputMode === 'text') {
      if (!formData.content.trim()) {
        toast.error('请输入题目内容')
        return
      }
      submitMutation.mutate({
        ...formData,
        tags: formData.tags ? formData.tags.split(',').map(t => t.trim()) : [],
      })
    } else {
      if (!selectedFile) {
        toast.error('请上传题目图片')
        return
      }
      submitImageMutation.mutate()
    }
  }

  const isProcessing = submitMutation.isPending || submitImageMutation.isPending || polling

  return (
    <div className="max-w-3xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-white mb-2">
          录入错题
        </h1>
        <p className="text-slate-400">
          输入题目内容或上传图片，AI将自动分析错因并生成举一反三题目
        </p>
      </div>

      {/* 输入模式切换 */}
      <div className="card p-4 mb-6">
        <div className="flex gap-4">
          <button
            type="button"
            onClick={() => setInputMode('text')}
            className={`flex-1 py-3 px-4 rounded-xl font-medium transition-all ${
              inputMode === 'text'
                ? 'bg-primary-500 text-white'
                : 'bg-slate-800/50 text-slate-400 hover:bg-slate-700/50'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <BookOpen className="w-5 h-5" />
              文字输入
            </div>
          </button>
          <button
            type="button"
            onClick={() => setInputMode('image')}
            className={`flex-1 py-3 px-4 rounded-xl font-medium transition-all ${
              inputMode === 'image'
                ? 'bg-primary-500 text-white'
                : 'bg-slate-800/50 text-slate-400 hover:bg-slate-700/50'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <ImagePlus className="w-5 h-5" />
              图片上传
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
              <label className="block text-sm font-medium text-slate-300 mb-2">
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
              <label className="block text-sm font-medium text-slate-300 mb-2">
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
            <label className="block text-sm font-medium text-slate-300 mb-2">
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
              <label className="block text-sm font-medium text-slate-300 mb-2">
                上传题目图片 *
              </label>
              {!previewUrl ? (
                <div
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  className="border-2 border-dashed border-slate-600 rounded-xl p-8 text-center hover:border-primary-500 transition-colors cursor-pointer"
                >
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleFileInput}
                    className="hidden"
                    id="question-image-upload"
                  />
                  <label htmlFor="question-image-upload" className="cursor-pointer">
                    <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Upload className="w-8 h-8 text-slate-400" />
                    </div>
                    <p className="text-white font-medium mb-2">
                      点击或拖拽上传题目图片
                    </p>
                    <p className="text-slate-500 text-sm">
                      支持 JPG、PNG、HEIC 格式，AI将自动识别题目内容
                    </p>
                  </label>

                  {/* 拍照按钮 */}
                  <div className="mt-6 pt-6 border-t border-slate-700">
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleFileInput}
                      className="hidden"
                      id="question-camera-capture"
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
                    className="w-full rounded-xl cursor-pointer transition-all group-hover:brightness-110"
                    onClick={() => setViewerOpen(true)}
                  />
                  <button
                    type="button"
                    onClick={clearImage}
                    className="absolute top-2 right-2 p-2 bg-slate-900/80 rounded-full hover:bg-slate-800 transition-colors z-10"
                  >
                    <X className="w-5 h-5 text-white" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      setViewerOpen(true)
                    }}
                    className="absolute top-2 left-2 p-2 bg-slate-900/80 rounded-full hover:bg-slate-800 transition-colors opacity-0 group-hover:opacity-100"
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
                <label className="block text-sm font-medium text-slate-300 mb-2">
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
                <label className="block text-sm font-medium text-slate-300 mb-2">
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
                <label className="block text-sm font-medium text-slate-300 mb-2">
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
                <label className="block text-sm font-medium text-slate-300 mb-2">
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
        {taskStatus && (
          <div className={`card p-4 ${
            taskStatus === 'completed' ? 'bg-emerald-500/10 border-emerald-500/30' :
            taskStatus === 'failed' ? 'bg-red-500/10 border-red-500/30' :
            'bg-primary-500/10 border-primary-500/30'
          }`}>
            <div className="flex items-center gap-3">
              {taskStatus === 'completed' ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              ) : taskStatus === 'failed' ? (
                <AlertCircle className="w-5 h-5 text-red-400" />
              ) : (
                <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
              )}
              <div>
                <p className="text-white font-medium">
                  {taskStatus === 'completed' ? '分析完成！即将跳转...' :
                   taskStatus === 'failed' ? '处理失败' :
                   taskStatus === 'processing' ? inputMode === 'image' ? 'AI正在识别和分析...' : 'AI正在分析中...' :
                   '任务已提交，等待处理...'}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Submit button */}
        <button
          type="submit"
          disabled={isProcessing}
          className="btn-primary w-full flex items-center justify-center gap-2 text-lg py-4"
        >
          {isProcessing ? (
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
