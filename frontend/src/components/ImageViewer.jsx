import { useState, useEffect } from 'react'
import { X, ZoomIn, ZoomOut, RotateCw, Download, Maximize2 } from 'lucide-react'

/**
 * 现代化图片查看器组件
 * 支持放大、缩放、旋转、下载等功能
 * 适配移动端和桌面端
 */
export default function ImageViewer({ isOpen, onClose, imageUrl, title = '查看图片' }) {
  const [scale, setScale] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  // 重置状态
  useEffect(() => {
    if (isOpen) {
      setScale(1)
      setRotation(0)
      setPosition({ x: 0, y: 0 })
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
  const handleRotate = () => setRotation(r => (r + 90) % 360)
  const handleReset = () => {
    setScale(1)
    setRotation(0)
    setPosition({ x: 0, y: 0 })
  }

  const handleDownload = async () => {
    try {
      const response = await fetch(imageUrl)
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `image_${Date.now()}.png`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const handleMouseDown = (e) => {
    if (scale > 1) {
      setIsDragging(true)
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y })
    }
  }

  const handleMouseMove = (e) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      })
    }
  }

  const handleMouseUp = () => {
    setIsDragging(false)
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
          <h2 className="text-white font-semibold text-lg">{title}</h2>
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
            onClick={handleRotate}
            className="p-3 rounded-xl bg-white/10 hover:bg-white/20 transition-all"
            title="旋转"
          >
            <RotateCw className="w-5 h-5 text-white" />
          </button>

          <button
            onClick={handleDownload}
            className="p-3 rounded-xl bg-white/10 hover:bg-white/20 transition-all"
            title="下载"
          >
            <Download className="w-5 h-5 text-white" />
          </button>
        </div>
      </div>

      {/* 图片容器 */}
      <div
        className="relative w-full h-full flex items-center justify-center p-20"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        style={{ cursor: scale > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
      >
        <img
          src={imageUrl}
          alt={title}
          className="max-w-full max-h-full object-contain select-none transition-transform duration-200"
          style={{
            transform: `scale(${scale}) rotate(${rotation}deg) translate(${position.x / scale}px, ${position.y / scale}px)`,
            transformOrigin: 'center',
          }}
          draggable={false}
        />
      </div>

      {/* 提示文字 */}
      <div className="absolute top-24 left-1/2 -translate-x-1/2 text-white/60 text-sm pointer-events-none">
        {scale > 1 ? '拖拽移动 · 滚轮缩放' : '滚轮缩放 · ESC 关闭'}
      </div>
    </div>
  )
}

