import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { companionApi } from '../lib/api'
import { MODULE_DESCRIPTIONS, SUBJECT_NAMES_CN, SUBJECT_TO_MODULE } from '../config/moduleRouting'
import { Sparkles, Send, MessageCircle, History, Plus, Search, Square, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

function getSubjectOptions() {
  const all = Object.keys(SUBJECT_TO_MODULE || {})
  const preferred = [
    'history', 'geography', 'other',
    'math', 'physics', 'chemistry',
    'chinese', 'english', 'politics',
    'economics',
  ]
  const set = new Set()
  const out = []
  for (const s of preferred) {
    if (all.includes(s) && !set.has(s)) { out.push(s); set.add(s) }
  }
  for (const s of all) {
    if (!set.has(s)) { out.push(s); set.add(s) }
  }
  return out
}

export default function Companion() {
  const [subject, setSubject] = useState('history')
  const [conversationId, setConversationId] = useState(null)
  const [mode, setMode] = useState('chat')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [sending, setSending] = useState(false)
  const [search, setSearch] = useState('')
  const [isComposingNew, setIsComposingNew] = useState(false)
  const [availability, setAvailability] = useState({ ok: true, message: '' })
  const listEndRef = useRef(null)
  const abortRef = useRef(null)

  const subjectOptions = useMemo(() => getSubjectOptions(), [])
  const subjectModule = SUBJECT_TO_MODULE?.[subject] || 'default'
  const subjectLabel = SUBJECT_NAMES_CN?.[subject] || subject

  const { data: convList, refetch: refetchConversations } = useQuery({
    queryKey: ['companion-conversations', { subject }],
    queryFn: () => companionApi.listConversations(subject, 20),
    retry: false,
    onError: (e) => {
      // If module is not implemented / not available, show a friendly banner and disable sending.
      const status = e?.response?.status
      const detail = e?.response?.data?.detail
      const msg = (typeof detail === 'string'
        ? detail
        : (detail?.detail || e?.message || '服务不可用')
      )
      if (status && status >= 400) {
        setAvailability({
          ok: false,
          message: `当前学科（${subjectLabel}）的小书童暂不可用：${msg}`,
        })
      } else {
        setAvailability({
          ok: false,
          message: `当前学科（${subjectLabel}）的小书童暂不可用：${e?.message || '网络异常'}`,
        })
      }
    },
    onSuccess: () => {
      setAvailability({ ok: true, message: '' })
    },
  })

  const conversations = useMemo(() => convList?.data?.items || [], [convList])
  const selectedConversation = useMemo(() => {
    if (!conversationId) return null
    return (conversations || []).find((c) => String(c.id) === String(conversationId)) || null
  }, [conversations, conversationId])

  // Auto-load latest conversation
  useEffect(() => {
    if (!conversationId && !isComposingNew && conversations.length > 0) {
      setConversationId(conversations[0].id)
    }
  }, [conversationId, conversations, isComposingNew])

  const { data: convData, refetch: refetchConv } = useQuery({
    queryKey: ['companion-conversation', { subject, conversationId }],
    // Important: while streaming, do NOT refresh from DB, otherwise it overwrites
    // the in-flight assistant message and user sees "空响应".
    enabled: !!conversationId && !sending,
    queryFn: () => companionApi.getConversation(conversationId, subject),
  })

  useEffect(() => {
    if (convData?.data?.messages) {
      // Same protection as above: avoid overwriting local streaming content.
      if (!sending) setMessages(convData.data.messages)
    }
  }, [convData, sending])

  useEffect(() => {
    // Always scroll to bottom on new messages
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  const startNewChat = () => {
    abortRef.current?.abort?.()
    abortRef.current = null
    setIsComposingNew(true)
    setConversationId(null)
    setMessages([])
    setInput('')
  }

  const stopStreaming = () => {
    abortRef.current?.abort?.()
    abortRef.current = null
    setSending(false)
    setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)))
  }

  const deleteConversation = async (id) => {
    if (!id) return
    if (sending) stopStreaming()
    const ok = window.confirm('确认删除该会话？（会同时删除该会话下的全部消息）')
    if (!ok) return
    try {
      await companionApi.deleteConversation(id, subject)
      // Refresh list
      await refetchConversations()
      // If deleting current conversation, go to next best: latest remaining or new chat.
      if (String(conversationId) === String(id)) {
        const remaining = (conversations || []).filter((c) => String(c.id) !== String(id))
        if (remaining.length > 0) {
          setIsComposingNew(false)
          setConversationId(remaining[0].id)
        } else {
          startNewChat()
        }
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || '删除失败'
      alert(`删除失败：${msg}`)
    }
  }

  const formatWhen = (iso) => {
    try {
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return iso || ''
      return d.toLocaleString()
    } catch {
      return iso || ''
    }
  }

  const groupConversations = (items) => {
    const now = new Date()
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000
    const groups = { 今天: [], 昨天: [], 更早: [] }

    for (const c of items || []) {
      const ts = new Date(c.updated_at || c.created_at || 0).getTime()
      if (ts >= startOfToday) groups['今天'].push(c)
      else if (ts >= startOfYesterday) groups['昨天'].push(c)
      else groups['更早'].push(c)
    }
    return groups
  }

  const send = async () => {
    const text = (input || '').trim()
    if (!text || sending) return
    if (!availability.ok) {
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, role: 'assistant', content: `当前学科暂不可用：${availability.message}`, created_at: new Date().toISOString() },
      ])
      return
    }

    setSending(true)
    setInput('')

    // optimistic user message
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: 'user', content: text, created_at: new Date().toISOString() },
    ])

    try {
      // Streaming first (SSE). Fallback to non-streaming if stream fails.
      const assistantId = `assistant-stream-${Date.now()}`
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: 'assistant', content: '', created_at: new Date().toISOString(), streaming: true },
      ])

      const controller = new AbortController()
      abortRef.current = controller
      const resp = await companionApi.chatStream({
        subject,
        message: text,
        conversation_id: conversationId,
        mode,
        signal: controller.signal,
      })

      if (!resp.ok) {
        // try to read JSON error
        let detail = `HTTP ${resp.status}`
        try {
          const j = await resp.json()
          detail = j?.detail || JSON.stringify(j)
        } catch {
          try {
            detail = await resp.text()
          } catch {
            detail = `HTTP ${resp.status}`
          }
        }
        setAvailability({ ok: false, message: String(detail || '服务不可用') })
        throw new Error(detail)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('No response body (stream unsupported)')

      const decoder = new TextDecoder('utf-8')
      let buf = ''
      let gotAnyDelta = false
      let finalRetrieved = null

      // SSE parser: split by blank line
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        // Support both LF and CRLF SSE framing
        const parts = buf.split(/\r?\n\r?\n/)
        buf = parts.pop() || ''

        for (const chunk of parts) {
          const lines = chunk.split(/\r?\n/)
          const dataLines = lines
            .map((l) => (typeof l === 'string' ? l.trimEnd() : ''))
            .filter((l) => l.startsWith('data:'))
          if (dataLines.length === 0) continue
          const dataStr = dataLines
            .map((l) => l.replace(/^data:\s?/, '').trimEnd())
            .join('\n')
          let evt = null
          try {
            evt = JSON.parse(dataStr)
          } catch {
            continue
          }

          if (evt?.type === 'meta') {
            if (evt?.conversation_id && !conversationId) {
              setConversationId(evt.conversation_id)
              setIsComposingNew(false)
            }
            // Non-blocking warning: subject LoRA not found -> backend may fall back to default model.
            if (evt?.warning) {
              setAvailability({ ok: true, message: String(evt.warning) })
              // Clear after a short while; keep UI clean.
              setTimeout(() => setAvailability({ ok: true, message: '' }), 6000)
            }
          } else if (evt?.type === 'delta') {
            gotAnyDelta = true
            const delta = evt?.content || ''
            if (!delta) continue
            setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: (m.content || '') + delta } : m)))
          } else if (evt?.type === 'done') {
            finalRetrieved = evt?.retrieved || null
            const full = evt?.assistant_message || ''
            setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: full || m.content || '（空响应）', streaming: false, retrieved: finalRetrieved } : m)))
          } else if (evt?.type === 'error') {
            const msg = evt?.message || '发送失败'
            setAvailability({ ok: false, message: String(msg) })
            throw new Error(msg)
          }
        }
      }

      // If stream ended without a done event, keep what we got.
      if (!gotAnyDelta) {
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: m.content || '（空响应）', streaming: false } : m)))
      }

      setTimeout(() => {
        refetchConv()
      }, 200)
    } catch (e) {
      if (String(e?.name || '') === 'AbortError') {
        setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)))
        return
      }
      const msg = e?.response?.data?.detail || e?.message || '发送失败'
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, role: 'assistant', content: `请求失败：${msg}`, created_at: new Date().toISOString() },
      ])
    } finally {
      abortRef.current = null
      setSending(false)
    }
  }

  const renderAssistantMarkdown = (raw) => {
    const s = String(raw || '').trim()
    return (
      <div className="prose prose-invert max-w-none prose-p:my-2 prose-pre:bg-slate-950/60 prose-pre:border prose-pre:border-slate-700/60">
        <ReactMarkdown>{s || '（无可展示内容）'}</ReactMarkdown>
      </div>
    )
  }

  const splitThinkAndAnswer = (raw) => {
    const s = String(raw || '')
    const startTag = '<think>'
    const endTag = '</think>'
    const start = s.indexOf(startTag)
    if (start < 0) {
      return { think: '', answer: s.trim(), inThinking: false }
    }
    const end = s.indexOf(endTag, start + startTag.length)
    if (end < 0) {
      // still streaming think
      const before = s.slice(0, start).trim()
      const think = s.slice(start + startTag.length).trim()
      return { think, answer: before, inThinking: true }
    }
    const before = s.slice(0, start).trim()
    const think = s.slice(start + startTag.length, end).trim()
    const after = s.slice(end + endTag.length).trim()
    // If there is text before <think>, keep it as part of answer.
    const answer = [before, after].filter(Boolean).join('\n\n').trim()
    return { think, answer, inThinking: false }
  }

  const filteredConversations = useMemo(() => {
    const q = (search || '').trim().toLowerCase()
    if (!q) return conversations
    return (conversations || []).filter((c) => String(c.title || '').toLowerCase().includes(q) || String(c.id || '').includes(q))
  }, [conversations, search])
  const grouped = useMemo(() => groupConversations(filteredConversations), [filteredConversations])

  return (
    <div className="max-w-6xl mx-auto animate-fade-in">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Gemini-like left sidebar */}
        <div className="card lg:col-span-4 xl:col-span-3 p-3 flex flex-col min-h-[720px]">
          <div className="p-2">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <div className="min-w-0">
                <div className="font-display font-bold text-white leading-tight">小书童</div>
                <div className="text-xs text-slate-500 leading-tight">对话 / 学习建议 / 复习陪练</div>
              </div>
            </div>

            <button
              onClick={startNewChat}
              className="mt-3 w-full btn-secondary flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              新建对话
            </button>

            <div className="mt-3 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索会话"
                  className="input pl-9"
                />
              </div>
            </div>

            <div className="mt-3 flex items-center gap-2">
              <select
                value={subject}
                onChange={(e) => { setAvailability({ ok: true, message: '' }); setSubject(e.target.value); startNewChat() }}
                className="input w-full"
              >
                {subjectOptions.map((s) => (
                  <option key={s} value={s}>
                    {SUBJECT_NAMES_CN?.[s] || s}（{SUBJECT_TO_MODULE?.[s] || 'default'}）
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="px-2 pb-2 text-xs text-slate-500 flex items-center gap-2">
            <History className="w-4 h-4" />
            {subjectLabel} 对话
          </div>

          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-4">
            {Object.entries(grouped).map(([label, items]) => (
              <div key={label}>
                <div className="text-xs text-slate-500 px-2 mb-2">{label}</div>
                <div className="space-y-1">
                  {(items || []).length === 0 ? null : items.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => { setIsComposingNew(false); setConversationId(c.id) }}
                      className={`group w-full text-left px-3 py-2 rounded-xl border transition-all relative ${
                        String(conversationId) === String(c.id)
                          ? 'border-primary-500/40 bg-primary-500/10 text-white'
                          : 'border-transparent hover:border-slate-700/60 hover:bg-slate-800/40 text-slate-300'
                      }`}
                    >
                      <button
                        type="button"
                        title="删除会话"
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); deleteConversation(c.id) }}
                        className="absolute right-2 top-2 p-1.5 rounded-lg text-slate-500 hover:text-red-300 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      <div className="text-sm font-medium line-clamp-1">{c.title || `会话 ${c.id}`}</div>
                      <div className="text-[11px] text-slate-500 mt-0.5 line-clamp-1">
                        {formatWhen(c.updated_at || c.created_at)}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}

            {(filteredConversations || []).length === 0 ? (
              <div className="text-slate-500 text-sm py-10 text-center">
                {search?.trim() ? '没有匹配的会话' : '暂无会话，点“新建对话”开始吧'}
              </div>
            ) : null}
          </div>

          <div className="px-2 pb-2 text-xs text-slate-500">
            模块：{subjectModule}（{MODULE_DESCRIPTIONS?.[subjectModule] || '模块说明缺失'}）
          </div>
        </div>

        {/* Right chat panel */}
        <div className="card lg:col-span-8 xl:col-span-9 flex flex-col min-h-[720px]">
          {/* Top bar */}
          <div className="px-5 py-4 border-b border-slate-800/50 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-slate-200 font-semibold">
                <MessageCircle className="w-4 h-4 text-slate-400" />
                <span className="truncate">
                  {selectedConversation?.title || (isComposingNew || !conversationId ? '新对话' : `会话 ${conversationId || ''}`)}
                </span>
              </div>
              <div className="text-xs text-slate-500 mt-1">
                {selectedConversation?.updated_at || selectedConversation?.created_at ? `更新时间：${formatWhen(selectedConversation.updated_at || selectedConversation.created_at)}` : 'Gemini 风格的对话体验（课堂版）'}
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => setMode('chat')}
                className={`px-3 py-1.5 rounded-full text-xs border ${
                  mode === 'chat' ? 'bg-primary-500/15 border-primary-500/30 text-primary-200' : 'border-slate-700/60 text-slate-300 hover:bg-slate-800/40'
                }`}
              >
                对话
              </button>
              <button
                onClick={() => setMode('learning_advice')}
                className={`px-3 py-1.5 rounded-full text-xs border ${
                  mode === 'learning_advice' ? 'bg-primary-500/15 border-primary-500/30 text-primary-200' : 'border-slate-700/60 text-slate-300 hover:bg-slate-800/40'
                }`}
              >
                学习建议
              </button>
              <button
                onClick={() => setMode('review')}
                className={`px-3 py-1.5 rounded-full text-xs border ${
                  mode === 'review' ? 'bg-primary-500/15 border-primary-500/30 text-primary-200' : 'border-slate-700/60 text-slate-300 hover:bg-slate-800/40'
                }`}
              >
                复习陪练
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {!availability.ok ? (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-amber-200 text-sm">
                {availability.message || '当前学科的小书童暂不可用。'}
                <div className="text-xs text-amber-200/80 mt-1">
                  提示：该学科会路由到模块 <span className="font-mono">{subjectModule}</span>。如果模块服务/模型未启动，请先启动对应模块与模型服务后重试。
                </div>
              </div>
            ) : null}
            {messages.length === 0 ? (
              <div className="text-slate-500 text-sm py-16 text-center">
                试试问：我最近薄弱点是什么？给我一周复习计划；或者直接把一道题的困惑发给我。
              </div>
            ) : (
              messages.map((m) => (
                <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-4 py-3 leading-relaxed ${
                    m.role === 'user'
                      ? 'bg-primary-500/20 border border-primary-500/30 text-slate-100'
                      : 'bg-slate-800/50 border border-slate-700/50 text-slate-200'
                  }`}>
                    {m.role === 'assistant'
                      ? (() => {
                        const { think, answer, inThinking } = splitThinkAndAnswer(m.content)
                        return (
                          <div className="space-y-3">
                            {(think || inThinking) ? (
                              <div className="rounded-xl border border-slate-700/60 bg-slate-950/40 px-3 py-2">
                                <div className="text-xs text-slate-400 mb-1">思考过程（think）</div>
                                <div className="text-xs leading-relaxed whitespace-pre-wrap font-mono text-slate-300">
                                  {think || '（思考中…）'}
                                </div>
                              </div>
                            ) : null}

                            {answer ? (
                              renderAssistantMarkdown(answer)
                            ) : (
                              <div className="text-slate-400">
                                {m.streaming ? '正在生成回答…' : '（无内容）'}
                              </div>
                            )}
                          </div>
                        )
                      })()
                      : <div className="whitespace-pre-wrap">{m.content}</div>
                    }
                  </div>
                </div>
              ))
            )}
            <div ref={listEndRef} />
          </div>

          {/* Bottom composer (sticky / gemini-like) */}
          <div className="px-5 pb-5">
            <div className="bg-slate-900/40 backdrop-blur-sm border border-slate-800/60 rounded-2xl p-3">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
                placeholder="输入你的问题（Enter 发送，Shift+Enter 换行）"
                className="w-full bg-transparent outline-none text-slate-100 placeholder-slate-500 resize-none min-h-[52px] max-h-[180px]"
                disabled={sending || !availability.ok}
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <div className="text-xs text-slate-500">
                  {!availability.ok ? '当前学科不可用，请切换学科或启动对应模块/模型' : (sending ? '流式生成中…' : '提示：输出支持 Markdown（表格/代码块等）')}
                </div>
                <div className="flex items-center gap-2">
                  {sending ? (
                    <button onClick={stopStreaming} className="btn-secondary px-4 py-2 flex items-center gap-2">
                      <Square className="w-4 h-4" />
                      停止
                    </button>
                  ) : null}
                  <button
                    onClick={send}
                    disabled={sending || !input.trim() || !availability.ok}
                    className="btn-primary px-5 py-2 flex items-center gap-2"
                  >
                    <Send className="w-4 h-4" />
                    发送
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

