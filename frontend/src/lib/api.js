import axios from 'axios'
import { getApiBaseUrl, getFullApiUrl } from '../config/moduleRouting'

/**
 * 创建动态 API 客户端
 * 根据学科自动路由到对应的模块
 * @param {string|null|undefined} subject - 学科名称（为空时使用默认模块处理跨学科查询）
 * @returns {AxiosInstance} Axios 实例
 */
export function createApiClient(subject) {
  // 当 subject 为空时，使用 null 以触发默认模块（端口 6100）
  // 这样可以支持跨学科查询（例如：获取所有学科的批改记录）
  const targetSubject = subject || null

  // getApiBaseUrl 已经返回 /api/{module}，所以这里只需要加 /v1
  // 例如：/api/tony/v1 -> Vite proxy 转发到 http://localhost:6005/api/v1
  const baseURL = `${getApiBaseUrl(targetSubject)}/v1`

  const client = axios.create({
    baseURL,
    headers: {
      'Content-Type': 'application/json',
    },
  })

  // Request interceptor to add auth token
  client.interceptors.request.use((config) => {
    // Debug 日志：记录请求信息
    if (import.meta.env.DEV) {
      console.debug('[API Request]', {
        subject: targetSubject || 'ALL',
        method: config.method?.toUpperCase(),
        url: config.url,
        baseURL: config.baseURL,
        data: config.data,
        params: config.params,
      })
    }

    const authStorage = localStorage.getItem('auth-storage')
    if (authStorage) {
      const { state } = JSON.parse(authStorage)
      if (state?.token) {
        config.headers.Authorization = `Bearer ${state.token}`
      }
    }
    return config
  })

  // Response interceptor for error handling
  client.interceptors.response.use(
    (response) => {
      // Debug 日志：记录成功响应
      if (import.meta.env.DEV) {
        console.debug('[API Response]', {
          subject: targetSubject || 'ALL',
          status: response.status,
          url: response.config.url,
          data: response.data,
        })
      }
      return response
    },
    (error) => {
      // Debug 日志：记录错误响应
      if (import.meta.env.DEV) {
        console.debug('[API Error]', {
          subject: targetSubject || 'ALL',
          status: error.response?.status,
          url: error.config?.url,
          method: error.config?.method?.toUpperCase(),
          data: error.response?.data,
          message: error.message,
        })
      }

      if (error.response?.status === 401) {
        // Clear auth state on 401
        localStorage.removeItem('auth-storage')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  return client
}

/**
 * 获取默认学科（从localStorage或默认值）
 */
function getDefaultSubject() {
  return localStorage.getItem('lastSelectedSubject') || 'math'
}

/**
 * 保存最后选择的学科
 * @param {string} subject - 学科名称
 */
function saveLastSubject(subject) {
  if (subject) {
    localStorage.setItem('lastSelectedSubject', subject)
  }
}

// ============================================
// Question APIs - 支持模块化路由
// ============================================
export const questionApi = {
  /**
   * 创建错题
   * @param {Object} data - 错题数据（必须包含 subject 字段）
   */
  create: (data) => {
    if (!data.subject) {
      throw new Error('Subject is required in question data')
    }
    saveLastSubject(data.subject)
    return createApiClient(data.subject).post('/questions/', data)
  },

  /**
   * 获取错题列表
   * @param {Object} params - 查询参数（必须包含 subject 字段）
   */
  list: (params = {}) => {
    const subject = params.subject || getDefaultSubject()
    saveLastSubject(subject)
    return createApiClient(subject).get('/questions/', { params })
  },

  /**
   * 获取错题详情
   * @param {number} id - 错题 ID
   * @param {string} subject - 学科名称
   */
  get: (id, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get(`/questions/${id}`)
  },

  /**
   * 更新错题
   * @param {number} id - 错题 ID
   * @param {Object} data - 更新数据
   * @param {string} subject - 学科名称
   */
  update: (id, data, subject) => {
    if (!subject) {
      subject = data.subject || getDefaultSubject()
    }
    return createApiClient(subject).patch(`/questions/${id}`, data)
  },

  /**
   * 删除错题
   * @param {number} id - 错题 ID
   * @param {string} subject - 学科名称
   */
  delete: (id, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).delete(`/questions/${id}`)
  },

  /**
   * 重新分析错题
   * @param {number} id - 错题 ID
   * @param {string} subject - 学科名称
   */
  reanalyze: (id, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).post(`/questions/${id}/reanalyze`)
  },

  /**
   * 查找相似题目
   * @param {Object} data - 查询数据（包含 question_id 或 content, 以及 subject）
   */
  findSimilar: (data) => {
    const subject = data.subject || getDefaultSubject()
    return createApiClient(subject).post('/questions/similar', data)
  },

  /**
   * 获取需要复习的错题
   * @param {Object} params - 查询参数（包含 subject）
   */
  getDueForReview: (params = {}) => {
    const subject = params.subject || getDefaultSubject()
    return createApiClient(subject).get('/questions/review/due', { params })
  },
}

// ============================================
// OCR APIs - 支持模块化路由
// ============================================
export const ocrApi = {
  /**
   * 上传试卷进行 OCR 识别
   * @param {FormData} formData - 包含图片和学科信息的表单数据
   * @param {string} subject - 学科名称
   */
  uploadExam: (formData, subject) => {
    if (!subject) {
      throw new Error('Subject is required for OCR upload')
    }
    saveLastSubject(subject)
    return createApiClient(subject).post('/ocr/analyze', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
}

// ============================================
// Corrections APIs - 支持模块化路由
// ============================================
export const correctionsApi = {
  /**
   * 获取批改历史
   * @param {Object} params - 查询参数（包含 subject）
   */
  list: (params = {}) => {
    const subject = params.subject || getDefaultSubject()
    return createApiClient(subject).get('/corrections/', { params })
  },

  /**
   * 获取批改详情
   * @param {number} id - 批改记录 ID
   * @param {string} subject - 学科名称
   */
  get: (id, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get(`/corrections/${id}`)
  },

  /**
   * 获取批改统计
   * @param {string} subject - 学科名称
   */
  getStats: (subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get('/corrections/stats')
  },
}

// ============================================
// Task APIs - 支持模块化路由
// ============================================
export const taskApi = {
  /**
   * 获取任务状态
   * @param {string} taskId - 任务 ID
   * @param {string} subject - 学科名称
   */
  getStatus: (taskId, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get(`/tasks/${taskId}`)
  },

  /**
   * 取消任务
   * @param {string} taskId - 任务 ID
   * @param {string} subject - 学科名称
   */
  cancel: (taskId, subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).delete(`/tasks/${taskId}`)
  },
}

// ============================================
// Learning APIs - 支持模块化路由
// ============================================
export const learningApi = {
  /**
   * 获取学习建议
   * @param {string} subject - 学科名称
   */
  getAdvice: (subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get('/learning/advice')
  },

  /**
   * 获取学习统计
   * @param {string} subject - 学科名称
   */
  getStats: (subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get('/learning/stats')
  },
}

// ============================================
// Feedback APIs - 支持模块化路由
// ============================================
export const feedbackApi = {
  /**
   * 创建反馈
   * @param {Object} data - 反馈数据（包含 subject）
   */
  create: (data) => {
    const subject = data.subject || getDefaultSubject()
    return createApiClient(subject).post('/feedback/', data)
  },

  /**
   * 获取反馈统计
   * @param {string} subject - 学科名称
   */
  getStats: (subject) => {
    if (!subject) {
      subject = getDefaultSubject()
    }
    return createApiClient(subject).get('/feedback/stats')
  },
}

// ============================================
// User/Auth APIs - 使用任意模块（认证是共享的）
// ============================================
// 认证 API 可以使用任意模块，因为所有模块共享认证系统
const authClient = createApiClient('chinese') // 使用 rpj 模块

export const authApi = {
  /**
   * 用户登录
   */
  login: (credentials) => authClient.post('/users/token', credentials),

  /**
   * 用户注册
   */
  register: (userData) => authClient.post('/users/register', userData),

  /**
   * 获取当前用户信息
   */
  getCurrentUser: () => authClient.get('/users/me'),

  /**
   * 获取用户信息
   */
  getUser: (userId) => authClient.get(`/users/${userId}`),
}

// ============================================
// Health Check APIs - 检查模块健康状态
// ============================================
export const healthApi = {
  /**
   * 检查指定模块的健康状态
   * @param {string} module - 模块名称
   */
  checkModule: async (module) => {
    try {
      const { getHealthCheckUrl } = await import('../config/moduleRouting')
      const url = getHealthCheckUrl(module)
      const response = await axios.get(url)
      return { module, healthy: true, data: response.data }
    } catch (error) {
      return { module, healthy: false, error: error.message }
    }
  },

  /**
   * 检查所有模块的健康状态
   */
  checkAllModules: async () => {
    const { getAllHealthCheckUrls } = await import('../config/moduleRouting')
    const urls = getAllHealthCheckUrls()
    const promises = Object.keys(urls).map(module => healthApi.checkModule(module))
    return Promise.all(promises)
  },
}

// 默认导出
export default {
  createApiClient,
  questionApi,
  ocrApi,
  correctionsApi,
  taskApi,
  learningApi,
  feedbackApi,
  authApi,
  healthApi,
}
