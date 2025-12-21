import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
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
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear auth state on 401
      localStorage.removeItem('auth-storage')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Question APIs
export const questionApi = {
  create: (data) => api.post('/questions/', data),
  list: (params) => api.get('/questions/', { params }),
  get: (id) => api.get(`/questions/${id}`),
  update: (id, data) => api.patch(`/questions/${id}`, data),
  delete: (id) => api.delete(`/questions/${id}`),
  reanalyze: (id) => api.post(`/questions/${id}/reanalyze`),
  findSimilar: (data) => api.post('/questions/similar', data),
  getDueForReview: (params) => api.get('/questions/review/due', { params }),
}

// Task APIs
export const taskApi = {
  getStatus: (taskId) => api.get(`/tasks/${taskId}`),
  cancel: (taskId) => api.delete(`/tasks/${taskId}`),
}

// Feedback APIs
export const feedbackApi = {
  create: (data) => api.post('/feedback/', data),
  getStats: () => api.get('/feedback/stats'),
}

