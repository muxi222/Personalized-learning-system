import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { api } from '../lib/api'

export const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: async (username, password) => {
        try {
          const response = await api.post('/users/token', { username, password })
          const { access_token } = response.data
          
          set({ token: access_token, isAuthenticated: true })
          
          // Fetch user info
          const userResponse = await api.get('/users/me')
          set({ user: userResponse.data })
          
          return { success: true }
        } catch (error) {
          return { 
            success: false, 
            error: error.response?.data?.detail || 'Login failed' 
          }
        }
      },

      register: async (userData) => {
        try {
          await api.post('/users/register', userData)
          // Auto login after registration
          return await get().login(userData.username, userData.password)
        } catch (error) {
          // 处理验证错误，显示详细的错误信息
          let errorMessage = '注册失败'
          
          if (error.response?.data) {
            const data = error.response.data
            
            // 处理 422 验证错误
            if (error.response.status === 422 && data.error_details) {
              // 解析验证错误详情
              const fieldErrors = data.error_details.map(err => {
                const field = err.field.replace('body -> ', '')
                let message = err.message
                
                // 友好的错误消息映射
                const fieldNames = {
                  'username': '用户名',
                  'email': '邮箱',
                  'password': '密码',
                  'full_name': '姓名',
                  'grade': '年级',
                }
                
                const fieldName = fieldNames[field] || field
                
                // 错误消息翻译
                if (message.includes('at least 3 characters')) {
                  message = '至少需要3个字符'
                } else if (message.includes('at least 6 characters')) {
                  message = '至少需要6个字符'
                } else if (message.includes('Invalid email')) {
                  message = '邮箱格式不正确'
                } else if (message.includes('value is not a valid email')) {
                  message = '邮箱格式不正确'
                }
                
                return `${fieldName}: ${message}`
              })
              
              errorMessage = fieldErrors.join('；')
            } else if (data.errors && Array.isArray(data.errors)) {
              // 兼容旧的错误格式
              errorMessage = data.errors.join('；')
            } else if (data.detail) {
              errorMessage = data.detail
            }
          }
          
          return { 
            success: false, 
            error: errorMessage,
            errorDetails: error.response?.data?.error_details || null
          }
        }
      },

      logout: () => {
        set({ user: null, token: null, isAuthenticated: false })
      },

      updateUser: (userData) => {
        set({ user: { ...get().user, ...userData } })
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ 
        token: state.token, 
        isAuthenticated: state.isAuthenticated,
        user: state.user,
      }),
    }
  )
)

