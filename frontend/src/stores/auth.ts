import { defineStore } from 'pinia'
import { api, clearToken, errMsg, getToken, setToken } from '../api'
import type { User } from '../types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    token: getToken(),
  }),
  getters: {
    isAdmin: (s) => s.user?.role === 'admin',
    isEditor: (s) => s.user?.role === 'admin' || s.user?.role === 'editor',
    displayName: (s) => s.user?.display_name || s.user?.username || '',
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await api.post('/auth/login', { username, password })
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
    },
    async register(username: string, password: string, displayName: string) {
      const { data } = await api.post('/auth/register', {
        username,
        password,
        display_name: displayName,
      })
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
    },
    async fetchMe() {
      try {
        const { data } = await api.get<User>('/auth/me')
        this.user = data
      } catch (e) {
        this.logout()
        throw e
      }
    },
    logout() {
      this.user = null
      this.token = null
      clearToken()
    },
    errorText(e: unknown) {
      return errMsg(e)
    },
  },
})