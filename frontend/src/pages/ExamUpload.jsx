import { useState, useCallback, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Camera,
  Upload,
  Loader2,
  CheckCircle2,
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
import SubjectFilter from '../components/SubjectFilter'
import { Link } from 'react-router-dom'
import ImageViewer from '../components/ImageViewer'
import ImageCompareViewer from '../components/ImageCompareViewer'
import { ocrApi } from '../lib/api' // 使用模块化API客户端

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

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

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

  return (
    <div className="animate-fade-in">
      <div className="section-heading">
        <h1>AI 智能批改</h1>
        <Link to="/corrections">批改历史 <ArrowLeftRight size={14} /></Link>
      </div>
      <div className="page-filters">
        <SubjectFilter value={subject} onChange={setSubject} name="exam-subject" disabled={analyzeMutation.isPending} />
        <div className="filter-row">
          <label className="filter-label" htmlFor="exam-grade">年级</label>
          <select id="exam-grade" value={grade} onChange={event => setGrade(event.target.value)} className="input w-auto text-sm py-1.5" disabled={analyzeMutation.isPending}>
            <option value="">不限年级</option>
            {['初一', '初二', '初三', '高一', '高二', '高三'].map(value => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
      </div>
      <div className="exam-grid">
        <section className="exam-upload-panel">
          <h2 className="exam-section-title"><span className="section-number">01</span>上传试卷</h2>
          {!previewUrl ? (
            <div className="upload-zone" onDrop={handleDrop} onDragOver={handleDragOver}>
              <input type="file" accept="image/*" onChange={handleFileInput} className="sr-only" id="file-upload" />
              <label htmlFor="file-upload">
                <span className="upload-icon"><Upload size={28} strokeWidth={1.5} /></span>
                <strong>选择试卷图片</strong>
                <small>JPG、PNG、HEIC</small>
              </label>
              <input type="file" accept="image/*" capture="environment" onChange={handleFileInput} className="sr-only" id="camera-capture" />
              <label htmlFor="camera-capture" className="btn-secondary camera-button"><Camera size={16} />拍照上传</label>
            </div>
          ) : (
            <>
              <div className="relative">
                <img src={previewUrl} alt="待批改的试卷" className="exam-preview" onClick={() => {
                  setViewerImage({ url: previewUrl, title: '原始试卷' })
                  setViewerOpen(true)
                }} />
                <button aria-label="移除试卷" title="移除试卷" disabled={analyzeMutation.isPending} onClick={clearSelection} className="absolute top-2 right-2 p-2 bg-white border border-slate-200 rounded-md text-slate-500 hover:text-red-600 disabled:opacity-50"><X size={16} /></button>
              </div>
              <p className="exam-file-name">{selectedFile?.name}</p>
            </>
          )}
          <button onClick={() => analyzeMutation.mutate()} disabled={!selectedFile || analyzeMutation.isPending} className="btn-primary w-full mt-5 gap-2">
            {analyzeMutation.isPending ? <><Loader2 size={17} className="animate-spin" />正在批改...</> : <><Sparkles size={17} />开始智能批改</>}
          </button>
        </section>
        <section className="exam-result-panel">
          <h2 className="exam-section-title"><span className="section-number">02</span>批改结果</h2>
          {analysisResult ? (
            <>
              {/* 总分卡片 */}
              <div className="card p-5 bg-primary-50 mb-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-slate-600 text-sm">总得分</p>
                    <div className="flex items-baseline gap-2 mt-1">
                      <span className="text-5xl font-bold text-slate-800">
                        {analysisResult.total_score}
                      </span>
                      <span className="text-2xl text-slate-500">
                        / {analysisResult.max_score}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-slate-600 text-sm">正确率</p>
                    <p className="text-2xl font-bold text-slate-800 mt-1">
                      {(analysisResult.accuracy_rate * 100).toFixed(0)}%
                    </p>
                  </div>
                </div>
              </div>

              {/* 题目详情 */}
              <div className="card p-6">
                <h3 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-primary-600" />
                  题目分析
                </h3>
                <div className="space-y-4">
                  {analysisResult.questions.map((q, index) => (
                    <div
                      key={index}
                      className={`p-4 rounded-lg border ${
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
                          <span className="text-slate-500 text-sm">
                            {q.question_type}
                          </span>
                        </div>
                        <span className={`font-bold ${
                          q.is_correct ? 'text-emerald-600' : 'text-red-600'
                        }`}>
                          {q.score}/{q.max_score}
                        </span>
                      </div>

                      <p className="text-slate-800 text-sm mb-2">
                        {q.question_text.slice(0, 100)}...
                      </p>

                      {!q.is_correct && (
                        <>
                          <div className="mt-3 p-3 bg-slate-50 rounded-lg">
                            <p className="text-red-600 text-sm mb-1">
                              <strong>你的答案:</strong> {q.student_answer}
                            </p>
                            <p className="text-emerald-600 text-sm">
                              <strong>正确答案:</strong> {q.correct_answer}
                            </p>
                          </div>
                          {q.error_analysis && (
                            <div className="mt-3 p-3 bg-amber-500/10 rounded-lg">
                              <p className="text-amber-600 text-sm">
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
                  <h3 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                    <Target className="w-5 h-5 text-amber-600" />
                    需要加强的知识点
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {analysisResult.weak_points.map((point, index) => (
                      <span
                        key={index}
                        className="px-3 py-2 bg-amber-500/10 text-amber-600 rounded-lg text-sm"
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
                  <h3 className="text-slate-800 font-semibold mb-4 flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-emerald-600" />
                    学习建议
                  </h3>
                  <ul className="space-y-2">
                    {analysisResult.improvement_suggestions.map((suggestion, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-3 text-slate-600"
                      >
                        <span className="w-6 h-6 bg-emerald-500/20 text-emerald-600 rounded-full flex items-center justify-center text-sm flex-shrink-0 mt-0.5">
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
                    <h3 className="text-slate-800 font-semibold">原始与批改对比</h3>
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
                      <div className="text-slate-500 text-sm mb-2 flex items-center gap-2">
                        <FileImage className="w-4 h-4" />
                        原始试卷
                      </div>
                      <div className="relative group cursor-pointer">
                        <img
                          src={previewUrl}
                          alt="原始试卷"
                          className="w-full rounded-lg transition-all group-hover:brightness-110"
                          onClick={() => {
                            setViewerImage({ url: previewUrl, title: '原始试卷' })
                            setViewerOpen(true)
                          }}
                        />
                        <div
                          className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 rounded-lg cursor-pointer"
                          onClick={(e) => {
                            e.stopPropagation()
                            setViewerImage({ url: previewUrl, title: '原始试卷' })
                            setViewerOpen(true)
                          }}
                        >
                          <div className="p-3 bg-black/60 backdrop-blur-sm rounded-lg">
                            <Maximize2 className="w-6 h-6 text-white" />
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 批改后试卷 */}
                    {correctedImageUrl && (
                      <div>
                        <div className="text-red-600 text-sm mb-2 flex items-center gap-2">
                          <CheckCircle2 className="w-4 h-4" />
                          批改后试卷
                        </div>
                        <div className="relative group cursor-pointer">
                          <img
                            src={correctedImageUrl}
                            alt="批改后试卷"
                            className="w-full rounded-lg transition-all group-hover:brightness-110"
                            onClick={() => {
                              setViewerImage({ url: correctedImageUrl, title: '批改后试卷' })
                              setViewerOpen(true)
                            }}
                          />
                          <div
                            className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 rounded-lg cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation()
                              setViewerImage({ url: correctedImageUrl, title: '批改后试卷' })
                              setViewerOpen(true)
                            }}
                          >
                            <div className="p-3 bg-black/60 backdrop-blur-sm rounded-lg">
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
            <div className="exam-empty" aria-live="polite">
              <img src="/exam-sheet.png" alt="" />
              <h3>{analyzeMutation.isPending ? '正在分析试卷' : '暂无批改结果'}</h3>
              <p>{analyzeMutation.isPending ? '请稍候，批改完成后将在这里显示' : '等待提交试卷'}</p>
            </div>
          )}
        </section>
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
