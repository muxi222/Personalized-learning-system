import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { createTaskMonitor, loadTaskState } from '../lib/taskStream'
import { getFullApiUrl } from '../config/moduleRouting'
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'

function getToken() {
  try {
    return JSON.parse(localStorage.getItem('auth-storage'))?.state?.token || null
  } catch {
    return null
  }
}

function buildImageFileContentUrl(imageId) {
  const token = getToken()
  const base = getFullApiUrl(null, `/image-files/${imageId}/content`)
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}

export default function TaskDetail() {
  const { taskId } = useParams()
  const [searchParams] = useSearchParams()
  const subject = (searchParams.get('subject') || '').trim() || null

  const [state, setState] = useState(() => (taskId ? (loadTaskState(taskId) || { task_id: taskId }) : null))
  const monitorRef = useRef(null)

  const imageId = useMemo(() => {
    const direct = state?.image_id
    if (typeof direct === 'number') return direct
    if (typeof direct === 'string' && direct.trim()) {
      const n = Number(direct)
      return Number.isFinite(n) ? n : null
    }
    return null
  }, [state])

  useEffect(() => {
    if (!taskId) return
    if (monitorRef.current) {
      monitorRef.current.stop()
      monitorRef.current = null
    }
    monitorRef.current = createTaskMonitor({
      taskId,
      subject,
      onUpdate: (s) => setState(s),
      onTerminal: () => {
        // keep the final snapshot visible
      },
    })
    return () => {
      if (monitorRef.current) {
        monitorRef.current.stop()
        monitorRef.current = null
      }
    }
  }, [taskId, subject])

  const status = state?.status || 'unknown'
  const progress = typeof state?.progress === 'number' ? state.progress : null
  const step = state?.current_step || ''
  const error = state?.error_message || ''
  const stages = state?.result?.stages && typeof state.result.stages === 'object' ? state.result.stages : null

  return (
    <div className="max-w-3xl mx-auto animate-fade-in space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold text-white mb-2">任务详情</h1>
          <div className="text-slate-400 text-sm break-all">
            task_id: {taskId}
          </div>
          {subject && (
            <div className="text-slate-400 text-sm">
              subject: {subject}
            </div>
          )}
        </div>
        <Link to="/submit" className="btn-secondary px-4 py-2 text-sm">返回录入页</Link>
      </div>

      <div className={`card p-4 ${
        status === 'completed' ? 'bg-emerald-500/10 border-emerald-500/30' :
        status === 'failed' ? 'bg-red-500/10 border-red-500/30' :
        'bg-primary-500/10 border-primary-500/30'
      }`}>
        <div className="flex items-start gap-3">
          {status === 'completed' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          ) : status === 'failed' ? (
            <AlertCircle className="w-5 h-5 text-red-400" />
          ) : (
            <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-white font-medium">
              {status === 'completed' ? '已完成' :
               status === 'failed' ? '失败' :
               status === 'processing' ? '处理中' :
               status === 'pending' ? '等待处理' :
               '状态未知'}
              {typeof progress === 'number' ? `（${Math.round(progress)}%）` : ''}
            </div>
            {step && <div className="text-sm text-slate-300 mt-1">{step}</div>}
            {status === 'failed' && error && <div className="text-sm text-red-300 mt-2 break-words">{error}</div>}
          </div>
        </div>
      </div>

      {imageId && (
        <div className="card p-4 space-y-3">
          <div className="text-white font-medium">图片内容</div>
          <img
            src={buildImageFileContentUrl(imageId)}
            alt="task image"
            className="w-full rounded-xl border border-slate-700/60"
          />
          <div className="text-xs text-slate-400 break-all">
            image_id: {imageId}
          </div>
        </div>
      )}

      <div className="card p-4 space-y-3">
        <div className="text-white font-medium">执行步骤 / 结果</div>
        {stages ? (
          <pre className="text-xs text-slate-300 whitespace-pre-wrap break-words bg-slate-900/40 border border-slate-700/60 rounded-lg p-3 overflow-auto max-h-[420px]">
            {JSON.stringify(stages, null, 2)}
          </pre>
        ) : (
          <div className="text-slate-400 text-sm">暂无阶段信息（任务尚未产生结果或后端未上报 stages）</div>
        )}
      </div>
    </div>
  )
}

