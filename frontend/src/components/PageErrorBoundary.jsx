import { Component } from 'react'
import { BookOpen } from 'lucide-react'

export default class PageErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    // Keep console signal for debugging in environments without overlays
    // eslint-disable-next-line no-console
    console.error('[PageErrorBoundary] render error:', error, info)
  }

  render() {
    const { hasError, error } = this.state
    if (!hasError) return this.props.children

    const message = error?.message ? String(error.message) : String(error || 'Unknown error')
    const stack = error?.stack ? String(error.stack) : ''
    const showDebug = Boolean(import.meta?.env?.DEV)

    return (
      <div className="card p-8">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-slate-800/60 flex items-center justify-center">
            <BookOpen className="w-6 h-6 text-slate-300" />
          </div>
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-white mb-1">页面渲染失败</h3>
            <p className="text-slate-300 break-words">{message}</p>

            {showDebug && stack && (
              <pre className="mt-4 p-4 rounded-xl bg-slate-950/60 border border-slate-800/60 text-xs text-slate-300 overflow-auto whitespace-pre-wrap">
                {stack}
              </pre>
            )}

            <div className="mt-6 flex gap-3">
              <button
                className="btn-secondary"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                重试
              </button>
              <a className="btn-primary" href="/questions">
                返回错题本
              </a>
            </div>
          </div>
        </div>
      </div>
    )
  }
}


