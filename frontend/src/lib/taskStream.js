import { getApiBaseUrl } from '../config/moduleRouting'
import { createApiClient } from './api'

const STORAGE_PREFIX = 'task_state:'
const ACTIVE_SET_KEY = 'task_active_ids'

function safeJsonParse(s) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

function nowIso() {
  return new Date().toISOString()
}

function deepMerge(base, patch) {
  if (base && patch && typeof base === 'object' && typeof patch === 'object' && !Array.isArray(base) && !Array.isArray(patch)) {
    const out = { ...base }
    Object.keys(patch).forEach((k) => {
      if (k in out) out[k] = deepMerge(out[k], patch[k])
      else out[k] = patch[k]
    })
    return out
  }
  return patch
}

export function applyTaskDelta(prevState, snapshotOrDelta) {
  const prev = prevState || {}
  const msg = snapshotOrDelta || {}

  // Normalize payloads (supports SSE snapshot/delta + polling TaskStatusResponse)
  const eventType = msg.event_type || (msg.patch ? 'delta' : 'snapshot')
  const status = msg.status || prev.status
  const progress = typeof msg.progress === 'number' ? msg.progress : prev.progress
  const currentStep = msg.current_step ?? prev.current_step
  const directImageId = msg.image_id ?? prev.image_id
  const errorMessage = msg.error_message ?? prev.error_message

  let result = prev.result && typeof prev.result === 'object' ? prev.result : {}
  let resultRev = typeof msg.result_rev === 'number' ? msg.result_rev : (prev.result_rev || 0)
  let lastPatch = msg.last_patch ?? prev.last_patch

  if (eventType === 'snapshot') {
    if (msg.result && typeof msg.result === 'object') {
      result = msg.result
      resultRev = typeof msg.result_rev === 'number'
        ? msg.result_rev
        : (typeof msg.result._rev === 'number' ? msg.result._rev : resultRev)
      lastPatch = msg.last_patch ?? msg.result?._last_patch ?? lastPatch
    }
  } else if (eventType === 'delta') {
    // SSE delta payload shape:
    // { patch: { stage: "ocr"|"reasoner"|..., patch: {...}, rev: number } }
    const p = msg.patch || msg.last_patch
    if (p && typeof p === 'object') {
      const stage = p.stage ?? null
      const patchObj = p.patch && typeof p.patch === 'object' ? p.patch : {}
      const rev = typeof p.rev === 'number' ? p.rev : undefined

      if (stage) {
        const stages = result.stages && typeof result.stages === 'object' ? result.stages : {}
        const prevStage = stages[stage] && typeof stages[stage] === 'object' ? stages[stage] : {}
        const nextStages = { ...stages, [stage]: deepMerge(prevStage, patchObj) }
        result = { ...result, stages: nextStages, _last_patch: p }
      } else {
        result = deepMerge(result, patchObj)
        result = { ...result, _last_patch: p }
      }

      if (typeof rev === 'number') {
        result = { ...result, _rev: rev }
        resultRev = rev
      }
      lastPatch = p
    }
  }

  // Infer image_id from merged result as a fallback (OCR intake stores it under stages.*)
  const imageIdFromResult = (() => {
    const stages = result?.stages
    if (!stages || typeof stages !== 'object') return null
    const v = stages?.saved?.source_image_id ?? stages?.uploaded?.image_id ?? stages?.uploaded?.source_image_id
    if (typeof v === 'number') return v
    if (typeof v === 'string' && v.trim()) {
      const n = Number(v)
      return Number.isFinite(n) ? n : null
    }
    return null
  })()
  const imageId = directImageId ?? imageIdFromResult ?? null

  return {
    ...prev,
    task_id: msg.task_id || prev.task_id,
    status,
    progress,
    current_step: currentStep,
    image_id: imageId,
    error_message: errorMessage,
    result,
    result_rev: resultRev,
    last_patch: lastPatch,
    updated_at: nowIso(),
  }
}

function getTaskBaseUrl(subject) {
  const baseWithoutV1 = getApiBaseUrl(subject || null)
  return baseWithoutV1 === '/api/v1' ? baseWithoutV1 : `${baseWithoutV1}/v1`
}

export function buildTaskStatusUrl(subject, taskId) {
  return `${getTaskBaseUrl(subject)}/tasks/${taskId}`
}

export function buildTaskStreamUrl(subject, taskId) {
  const token = safeJsonParse(localStorage.getItem('auth-storage'))?.state?.token
  const base = `${getTaskBaseUrl(subject)}/tasks/${taskId}/stream`
  // NOTE: EventSource can't send Authorization header; token is optional query param (backend may ignore it).
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}

function loadActiveIds() {
  const raw = localStorage.getItem(ACTIVE_SET_KEY)
  const arr = safeJsonParse(raw)
  return Array.isArray(arr) ? arr : []
}

function saveActiveIds(ids) {
  localStorage.setItem(ACTIVE_SET_KEY, JSON.stringify(ids.slice(0, 200)))
}

export function loadTaskState(taskId) {
  const raw = localStorage.getItem(`${STORAGE_PREFIX}${taskId}`)
  const parsed = safeJsonParse(raw)
  return parsed && typeof parsed === 'object' ? parsed : null
}

export function persistTaskState(taskId, state) {
  if (!taskId) return
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${taskId}`, JSON.stringify(state))
  } catch {
    // If storage is full, best-effort prune old tasks
    const ids = loadActiveIds()
    ids.slice(50).forEach((id) => localStorage.removeItem(`${STORAGE_PREFIX}${id}`))
    try {
      localStorage.setItem(`${STORAGE_PREFIX}${taskId}`, JSON.stringify(state))
    } catch {
      // ignore
    }
  }
}

function markTaskActive(taskId) {
  const ids = loadActiveIds()
  if (!ids.includes(taskId)) {
    ids.unshift(taskId)
    saveActiveIds(ids)
  }
}

function unmarkTaskActive(taskId) {
  const ids = loadActiveIds().filter((x) => x !== taskId)
  saveActiveIds(ids)
}

/**
 * Create a resilient monitor for a task:
 * - Prefer SSE (EventSource) when available
 * - Auto-reconnect with backoff
 * - Fallback to polling if SSE seems unavailable
 * - Persist merged state to localStorage for refresh/restart recovery
 */
export function createTaskMonitor({
  taskId,
  subject,
  onUpdate,
  onTerminal,
  preferSse = true,
  pollIntervalMs = 2000,
  sseFirstMessageTimeoutMs = 3000,
}) {
  if (!taskId) throw new Error('taskId is required')

  let closed = false
  let es = null
  let pollTimer = null
  let reconnectTimer = null
  let firstMsgTimer = null
  let reconnectAttempts = 0

  const client = createApiClient(subject || null)
  let state = loadTaskState(taskId) || { task_id: taskId }

  markTaskActive(taskId)
  onUpdate?.(state)

  const stop = () => {
    closed = true
    if (es) {
      try { es.close() } catch { /* ignore */ }
      es = null
    }
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (firstMsgTimer) {
      clearTimeout(firstMsgTimer)
      firstMsgTimer = null
    }
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const handleTerminal = (finalState) => {
    if (finalState?.status === 'completed' || finalState?.status === 'failed') {
      unmarkTaskActive(taskId)
      persistTaskState(taskId, finalState)
      onTerminal?.(finalState)
    }
  }

  const applyAndPublish = (incoming) => {
    state = applyTaskDelta(state, incoming)
    persistTaskState(taskId, state)
    onUpdate?.(state)
    handleTerminal(state)
  }

  const startPolling = () => {
    if (pollTimer || closed) return
    pollTimer = setInterval(async () => {
      try {
        const resp = await client.get(`/tasks/${taskId}`)
        applyAndPublish({ ...resp.data, event_type: 'snapshot' })
        if (state?.status === 'completed' || state?.status === 'failed') stop()
      } catch {
        // ignore (network flap)
      }
    }, pollIntervalMs)
  }

  const startSse = () => {
    if (closed || !preferSse || typeof window === 'undefined' || !window.EventSource) {
      startPolling()
      return
    }

    const url = buildTaskStreamUrl(subject, taskId)
    es = new EventSource(url)

    firstMsgTimer = setTimeout(() => {
      // If SSE isn't producing data quickly (404/no route/proxy issues), fallback to polling.
      if (!closed && reconnectAttempts === 0) startPolling()
    }, sseFirstMessageTimeoutMs)

    es.onmessage = (evt) => {
      if (firstMsgTimer) {
        clearTimeout(firstMsgTimer)
        firstMsgTimer = null
      }
      reconnectAttempts = 0
      // SSE is healthy; stop polling to reduce load
      stopPolling()
      try {
        const data = safeJsonParse(evt.data)
        if (!data) return
        applyAndPublish(data)
        if (state?.status === 'completed' || state?.status === 'failed') stop()
      } catch {
        // ignore parse errors
      }
    }

    es.addEventListener('close', () => {
      if (!closed) stop()
    })

    es.onerror = () => {
      if (closed) return
      reconnectAttempts += 1
      try { es.close() } catch { /* ignore */ }
      es = null

      // Keep polling running as safety net
      startPolling()

      // Exponential backoff reconnect (cap 10s)
      const delay = Math.min(10000, 250 * (2 ** Math.min(6, reconnectAttempts)))
      reconnectTimer = setTimeout(() => {
        if (!closed) startSse()
      }, delay)
    }
  }

  // Kick off: fetch once to get an immediate snapshot (also works after backend restart)
  ;(async () => {
    try {
      const resp = await client.get(`/tasks/${taskId}`)
      applyAndPublish({ ...resp.data, event_type: 'snapshot' })
    } catch {
      // ignore
    } finally {
      startSse()
    }
  })()

  return { stop }
}


