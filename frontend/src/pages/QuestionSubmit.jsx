import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { questionApi, taskApi } from '../lib/api'
import { 
  Send, 
  Loader2, 
  CheckCircle2,
  AlertCircle,
  BookOpen,
  ImagePlus
} from 'lucide-react'
import toast from 'react-hot-toast'

const SUBJECTS = [
  { value: 'math', label: '数学' },
  { value: 'physics', label: '物理' },
  { value: 'chemistry', label: '化学' },
  { value: 'biology', label: '生物' },
  { value: 'english', label: '英语' },
  { value: 'chinese', label: '语文' },
  { value: 'other', label: '其他' },
]

const DIFFICULTIES = [
  { value: 'easy', label: '简单' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困难' },
]

export default function QuestionSubmit() {
  const navigate = useNavigate()
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

  const handleSubmit = (e) => {
    e.preventDefault()
    
    if (!formData.content.trim()) {
      toast.error('请输入题目内容')
      return
    }

    submitMutation.mutate({
      ...formData,
      tags: formData.tags ? formData.tags.split(',').map(t => t.trim()) : [],
    })
  }

  const isProcessing = submitMutation.isPending || polling

  return (
    <div className="max-w-3xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-white mb-2">
          录入错题
        </h1>
        <p className="text-slate-400">
          输入题目内容，AI将自动分析错因并生成举一反三题目
        </p>
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
                   taskStatus === 'processing' ? 'AI正在分析中...' :
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
              处理中...
            </>
          ) : (
            <>
              <Send className="w-5 h-5" />
              提交分析
            </>
          )}
        </button>
      </form>
    </div>
  )
}

