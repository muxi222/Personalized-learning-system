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
          return { 
            success: false, 
            error: error.response?.data?.detail || 'Registration failed' 
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

