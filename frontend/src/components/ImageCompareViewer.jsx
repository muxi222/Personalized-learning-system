import { useState, useEffect } from 'react'
import { X, ZoomIn, ZoomOut, Download, ArrowLeftRight } from 'lucide-react'

/**
 * 图片对比查看器
 * 支持左右并排展示两张图片，同步缩放
 */
export default function ImageCompareViewer({ 
  isOpen, 
  onClose, 
  leftImage = { url: '', title: '原始' },
  rightImage = { url: '', title: '批改' }
}) {
  const [scale, setScale] = useState(1)
  const [showSplit, setShowSplit] = useState(true) // 显示分屏模式

  // 重置状态
  useEffect(() => {
    if (isOpen) {
      setScale(1)
      setShowSplit(true)
    }
  }, [isOpen])

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

  if (!isOpen) return null

  const handleZoomIn = () => setScale(s => Math.min(s + 0.25, 3))
  const handleZoomOut = () => setScale(s => Math.max(s - 0.25, 0.5))
  const handleReset = () => setScale(1)

  const handleDownload = async (url, filename) => {
    try {
      const response = await fetch(url)
      const blob = await response.blob()
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = filename || `image_${Date.now()}.png`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(downloadUrl)
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const handleWheel = (e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    setScale(s => Math.max(0.5, Math.min(3, s + delta)))
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      {/* 头部工具栏 */}
      <div
        className="absolute top-0 left-0 right-0 bg-gradient-to-b from-black/80 to-transparent p-6 z-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <h2 className="text-white font-semibold text-lg">对比查看</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
          >
            <X className="w-6 h-6 text-white" />
          </button>
        </div>
      </div>

      {/* 底部工具栏 */}
      <div
        className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-6 z-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="max-w-7xl mx-auto flex items-center justify-center gap-2">
          <button
            onClick={handleZoomOut}
            disabled={scale <= 0.5}
            className="p-3 rounded-xl bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            title="缩小"
          >
            <ZoomOut className="w-5 h-5 text-white" />
          </button>

          <button
            onClick={handleReset}
            className="px-4 py-3 rounded-xl bg-white/10 hover:bg-white/20 transition-all"
            title="重置"
          >
            <span className="text-white font-medium text-sm">
              {(scale * 100).toFixed(0)}%
            </span>
          </button>

          <button
            onClick={handleZoomIn}
            disabled={scale >= 3}
            className="p-3 rounded-xl bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            title="放大"
          >
            <ZoomIn className="w-5 h-5 text-white" />
          </button>

          <div className="w-px h-8 bg-white/20 mx-2" />

          <button
            onClick={() => handleDownload(leftImage.url, `${leftImage.title}.png`)}
            className="p-3 rounded-xl bg-white/10 hover:bg-white/20 transition-all"
            title="下载原始图片"
          >
            <Download className="w-5 h-5 text-white" />
            <span className="text-white text-xs ml-1">原始</span>
          </button>

          {rightImage.url && (
            <button
              onClick={() => handleDownload(rightImage.url, `${rightImage.title}.png`)}
              className="p-3 rounded-xl bg-white/10 hover:bg-white/20 transition-all"
              title="下载批改图片"
            >
              <Download className="w-5 h-5 text-white" />
              <span className="text-white text-xs ml-1">批改</span>
            </button>
          )}
        </div>
      </div>

      {/* 对比图片容器 */}
      <div
        className="relative w-full h-full flex items-center justify-center p-20 gap-4"
        onClick={(e) => e.stopPropagation()}
        onWheel={handleWheel}
      >
        {showSplit && rightImage.url ? (
          // 对比模式 - 左右分屏
          <div className="flex gap-4 w-full h-full items-center justify-center">
            {/* 左侧 - 原始图片 */}
            <div className="flex-1 h-full flex flex-col items-center">
              <div className="text-white/80 text-sm mb-3 bg-black/40 px-4 py-2 rounded-full backdrop-blur-sm">
                {leftImage.title}
              </div>
              <div className="flex-1 flex items-center justify-center overflow-hidden">
                <img
                  src={leftImage.url}
                  alt={leftImage.title}
                  className="max-w-full max-h-full object-contain select-none transition-transform duration-200"
                  style={{
                    transform: `scale(${scale})`,
                  }}
                  draggable={false}
                />
              </div>
            </div>

            {/* 中间分隔线 */}
            <div className="w-0.5 h-2/3 bg-white/30 relative">
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-black/60 backdrop-blur-sm rounded-full p-2">
                <ArrowLeftRight className="w-5 h-5 text-white" />
              </div>
            </div>

            {/* 右侧 - 批改图片 */}
            <div className="flex-1 h-full flex flex-col items-center">
              <div className="text-white/80 text-sm mb-3 bg-red-500/40 px-4 py-2 rounded-full backdrop-blur-sm">
                {rightImage.title}
              </div>
              <div className="flex-1 flex items-center justify-center overflow-hidden">
                <img
                  src={rightImage.url}
                  alt={rightImage.title}
                  className="max-w-full max-h-full object-contain select-none transition-transform duration-200"
                  style={{
                    transform: `scale(${scale})`,
                  }}
                  draggable={false}
                />
              </div>
            </div>
          </div>
        ) : (
          // 单图模式
          <div className="flex items-center justify-center w-full h-full">
            <img
              src={leftImage.url}
              alt={leftImage.title}
              className="max-w-full max-h-full object-contain select-none transition-transform duration-200"
              style={{
                transform: `scale(${scale})`,
              }}
              draggable={false}
            />
          </div>
        )}
      </div>

      {/* 提示文字 */}
      <div className="absolute top-24 left-1/2 -translate-x-1/2 text-white/60 text-sm pointer-events-none">
        滚轮缩放 · ESC 关闭 · 同步对比
      </div>
    </div>
  )
}

