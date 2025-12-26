import { useState, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Camera,
  Upload,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileImage,
  X,
  Sparkles,
  BookOpen,
  Target,
  TrendingUp,
  Maximize2,
  ArrowLeftRight
} from 'lucide-react'
import toast from 'react-hot-toast'
import ImageViewer from '../components/ImageViewer'
import ImageCompareViewer from '../components/ImageCompareViewer'
import { ocrApi } from '../lib/api' // 使用模块化API客户端

// 10个学科 - 对应5个模块
const SUBJECTS = [
  // RPJ模块 (6001)
  { value: 'chinese', label: '语文', icon: '📖', color: 'from-red-500 to-rose-500' },
  { value: 'english', label: '英语', icon: '🔤', color: 'from-green-500 to-emerald-500' },
  { value: 'politics', label: '政治', icon: '🏛️', color: 'from-slate-500 to-gray-500' },

  // XMX模块 (6002)
  { value: 'economics', label: '经济学', icon: '💹', color: 'from-yellow-500 to-amber-500' },

  // WZY模块 (6003)
  { value: 'math', label: '数学', icon: '📐', color: 'from-blue-500 to-indigo-500' },
  { value: 'physics', label: '物理', icon: '⚡', color: 'from-orange-500 to-red-500' },

  // WZM模块 (6004)
  { value: 'chemistry', label: '化学', icon: '🧪', color: 'from-purple-500 to-pink-500' },

  // TONY模块 (6005)
  { value: 'history', label: '历史', icon: '📜', color: 'from-brown-500 to-amber-700' },
  { value: 'geography', label: '地理', icon: '🌍', color: 'from-cyan-500 to-blue-500' },
  { value: 'other', label: '其他', icon: '📚', color: 'from-gray-500 to-slate-500' },
]

export default function ExamUpload() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [subject, setSubject] = useState('math')
  const [grade, setGrade] = useState('')
  const [analysisResult, setAnalysisResult] = useState(null)
  const [correctedImageUrl, setCorrectedImageUrl] = useState(null)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState({ url: '', title: '' })
  const [compareViewerOpen, setCompareViewerOpen] = useState(false)

  // 处理文件选择
  const handleFileSelect = useCallback((file) => {
    if (file && file.type.startsWith('image/')) {
      setSelectedFile(file)
      const url = URL.createObjectURL(file)
      setPreviewUrl(url)
      setAnalysisResult(null)
      setCorrectedImageUrl(null)
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

  // 文件上传
  const handleFileInput = useCallback((e) => {
    const file = e.target.files[0]
    handleFileSelect(file)
  }, [handleFileSelect])

  // 清除选择
  const clearSelection = useCallback(() => {
    setSelectedFile(null)
    setPreviewUrl(null)
    setAnalysisResult(null)
    setCorrectedImageUrl(null)
  }, [])

  // 分析试卷 - 使用模块化API
  const analyzeMutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('subject', subject)
      formData.append('grade', grade)

      // 使用模块化API客户端，自动路由到正确的模块
      const response = await ocrApi.uploadExam(formData, subject)
      return response.data
    },
    onSuccess: (data) => {
      setAnalysisResult(data)
      if (data.corrected_image_url) {
        setCorrectedImageUrl(data.corrected_image_url)
      }
      // 显示重复检测提示
      if (data.is_duplicate && data.duplicate_message) {
        toast(data.duplicate_message, {
          icon: '⚠️',
          duration: 4000,
        })
      }
      toast.success('分析完成！')
    },
    onError: (error) => {
      toast.error(error.message || '分析失败，请重试')
    }
  })

  const selectedSubject = SUBJECTS.find(s => s.value === subject)

  return (
    <div className="max-w-6xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-12 h-12 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-bold text-white">
              AI 智能批改
            </h1>
            <p className="text-slate-400">
              拍照上传试卷，AI 自动识别、批改、分析错因
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 左侧 - 上传区域 */}
        <div className="space-y-6">
          {/* 学科选择 */}
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4">选择学科</h3>
            <div className="grid grid-cols-3 gap-3">
              {SUBJECTS.map((s) => (
                <button
                  key={s.value}
                  onClick={() => setSubject(s.value)}
                  className={`p-4 rounded-xl border-2 transition-all ${
                    subject === s.value
                      ? 'border-primary-500 bg-primary-500/10'
                      : 'border-slate-700 hover:border-slate-600 bg-slate-800/50'
                  }`}
                >
                  <div className="text-2xl mb-2">{s.icon}</div>
                  <div className={`text-sm font-medium ${
                    subject === s.value ? 'text-primary-400' : 'text-slate-300'
                  }`}>
                    {s.label}
                  </div>
                </button>
              ))}
            </div>

            {/* 年级选择 */}
            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-300 mb-2">
                年级（可选）
              </label>
              <select
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
                className="input"
              >
                <option value="">请选择年级</option>
                <option value="初一">初一</option>
                <option value="初二">初二</option>
                <option value="初三">初三</option>
                <option value="高一">高一</option>
                <option value="高二">高二</option>
                <option value="高三">高三</option>
              </select>
            </div>
          </div>

          {/* 上传区域 */}
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4">上传试卷</h3>

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
                  id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer">
                  <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
                    <Upload className="w-8 h-8 text-slate-400" />
                  </div>
                  <p className="text-white font-medium mb-2">
                    点击或拖拽上传试卷图片
                  </p>
                  <p className="text-slate-500 text-sm">
                    支持 JPG、PNG、HEIC 格式
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
                    id="camera-capture"
                  />
                  <label
                    htmlFor="camera-capture"
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
                  alt="预览"
                  className="w-full rounded-xl cursor-pointer transition-all group-hover:brightness-110"
                  onClick={() => {
                    setViewerImage({ url: previewUrl, title: '原始试卷' })
                    setViewerOpen(true)
                  }}
                />
                <button
                  onClick={clearSelection}
                  className="absolute top-2 right-2 p-2 bg-slate-900/80 rounded-full hover:bg-slate-800 transition-colors z-10"
                >
                  <X className="w-5 h-5 text-white" />
                </button>
                {/* 放大提示 */}
                <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                  <div className="p-4 bg-black/60 backdrop-blur-sm rounded-2xl">
                    <Maximize2 className="w-8 h-8 text-white" />
                  </div>
                </div>
              </div>
            )}

            {/* 分析按钮 */}
            {selectedFile && (
              <button
                onClick={() => analyzeMutation.mutate()}
                disabled={analyzeMutation.isPending}
                className="btn-primary w-full mt-4 flex items-center justify-center gap-2 text-lg py-4"
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    AI 正在分析中...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    开始智能批改
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* 右侧 - 分析结果 */}
        <div className="space-y-6">
          {analysisResult ? (
            <>
              {/* 总分卡片 */}
              <div className={`card p-6 bg-gradient-to-r ${selectedSubject?.color || 'from-primary-500 to-accent-500'} bg-opacity-10`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-slate-300 text-sm">总得分</p>
                    <div className="flex items-baseline gap-2 mt-1">
                      <span className="text-5xl font-bold text-white">
                        {analysisResult.total_score}
                      </span>
                      <span className="text-2xl text-slate-400">
                        / {analysisResult.max_score}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-slate-300 text-sm">正确率</p>
                    <p className="text-3xl font-bold text-white mt-1">
                      {(analysisResult.accuracy_rate * 100).toFixed(0)}%
                    </p>
                  </div>
                </div>
              </div>

              {/* 题目详情 */}
              <div className="card p-6">
                <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-primary-400" />
                  题目分析
                </h3>
                <div className="space-y-4">
                  {analysisResult.questions.map((q, index) => (
                    <div
                      key={index}
                      className={`p-4 rounded-xl border ${
                        q.is_correct
                          ? 'border-emerald-500/30 bg-emerald-500/5'
                          : 'border-red-500/30 bg-red-500/5'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={`w-6 h-6 rounded-full flex items-center justify-center text-sm font-medium ${
                            q.is_correct
                              ? 'bg-emerald-500 text-white'
                              : 'bg-red-500 text-white'
                          }`}>
                            {q.question_number}
                          </span>
                          <span className="text-slate-400 text-sm">
                            {q.question_type}
                          </span>
                        </div>
                        <span className={`font-bold ${
                          q.is_correct ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {q.score}/{q.max_score}
                        </span>
                      </div>

                      <p className="text-white text-sm mb-2">
                        {q.question_text.slice(0, 100)}...
                      </p>

                      {!q.is_correct && (
                        <>
                          <div className="mt-3 p-3 bg-slate-800/50 rounded-lg">
                            <p className="text-red-400 text-sm mb-1">
                              <strong>你的答案:</strong> {q.student_answer}
                            </p>
                            <p className="text-emerald-400 text-sm">
                              <strong>正确答案:</strong> {q.correct_answer}
                            </p>
                          </div>
                          {q.error_analysis && (
                            <div className="mt-3 p-3 bg-amber-500/10 rounded-lg">
                              <p className="text-amber-400 text-sm">
                                <strong>错因分析:</strong> {q.error_analysis}
                              </p>
                            </div>
                          )}
                        </>
                      )}

                      {q.knowledge_points.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {q.knowledge_points.map((kp, i) => (
                            <span
                              key={i}
                              className="badge-primary text-xs"
                            >
                              {kp}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* 薄弱知识点 */}
              {analysisResult.weak_points.length > 0 && (
                <div className="card p-6">
                  <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                    <Target className="w-5 h-5 text-amber-400" />
                    需要加强的知识点
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {analysisResult.weak_points.map((point, index) => (
                      <span
                        key={index}
                        className="px-3 py-2 bg-amber-500/10 text-amber-400 rounded-lg text-sm"
                      >
                        {point}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* 学习建议 */}
              {analysisResult.improvement_suggestions.length > 0 && (
                <div className="card p-6">
                  <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-emerald-400" />
                    学习建议
                  </h3>
                  <ul className="space-y-2">
                    {analysisResult.improvement_suggestions.map((suggestion, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-3 text-slate-300"
                      >
                        <span className="w-6 h-6 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center text-sm flex-shrink-0 mt-0.5">
                          {index + 1}
                        </span>
                        {suggestion}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 原始与批改对比 */}
              {previewUrl && analysisResult && (
                <div className="card p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-white font-semibold">原始与批改对比</h3>
                    {correctedImageUrl && (
                      <button
                        onClick={() => setCompareViewerOpen(true)}
                        className="btn-primary px-4 py-2 text-sm flex items-center gap-2"
                      >
                        <ArrowLeftRight className="w-4 h-4" />
                        对比放大
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* 原始试卷 */}
                    <div>
                      <div className="text-slate-400 text-sm mb-2 flex items-center gap-2">
                        <FileImage className="w-4 h-4" />
                        原始试卷
                      </div>
                      <div className="relative group cursor-pointer">
                        <img
                          src={previewUrl}
                          alt="原始试卷"
                          className="w-full rounded-xl transition-all group-hover:brightness-110"
                          onClick={() => {
                            setViewerImage({ url: previewUrl, title: '原始试卷' })
                            setViewerOpen(true)
                          }}
                        />
                        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 rounded-xl">
                          <div className="p-3 bg-black/60 backdrop-blur-sm rounded-xl">
                            <Maximize2 className="w-6 h-6 text-white" />
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 批改后试卷 */}
                    {correctedImageUrl && (
                      <div>
                        <div className="text-red-400 text-sm mb-2 flex items-center gap-2">
                          <CheckCircle2 className="w-4 h-4" />
                          批改后试卷
                        </div>
                        <div className="relative group cursor-pointer">
                          <img
                            src={correctedImageUrl}
                            alt="批改后试卷"
                            className="w-full rounded-xl transition-all group-hover:brightness-110"
                            onClick={() => {
                              setViewerImage({ url: correctedImageUrl, title: '批改后试卷' })
                              setViewerOpen(true)
                            }}
                          />
                          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 rounded-xl">
                            <div className="p-3 bg-black/60 backdrop-blur-sm rounded-xl">
                              <Maximize2 className="w-6 h-6 text-white" />
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="card p-12 text-center">
              <div className="w-20 h-20 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
                <FileImage className="w-10 h-10 text-slate-600" />
              </div>
              <p className="text-slate-400 mb-2">
                上传试卷图片后，AI 将自动分析
              </p>
              <p className="text-slate-600 text-sm">
                支持手写和打印试卷
              </p>
            </div>
          )}
        </div>
      </div>

      {/* 单图查看器 */}
      <ImageViewer
        isOpen={viewerOpen}
        onClose={() => setViewerOpen(false)}
        imageUrl={viewerImage.url}
        title={viewerImage.title}
      />

      {/* 对比查看器 */}
      <ImageCompareViewer
        isOpen={compareViewerOpen}
        onClose={() => setCompareViewerOpen(false)}
        leftImage={{ url: previewUrl, title: '原始试卷' }}
        rightImage={{ url: correctedImageUrl, title: '批改后试卷' }}
      />
    </div>
  )
}
