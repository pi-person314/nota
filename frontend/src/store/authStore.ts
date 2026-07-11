import { create } from 'zustand'
import { api, ApiRequestError, type User } from '../lib/api'

type AuthResult = { ok: true } | { ok: false; message: string }

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiRequestError ? err.message : fallback
}

interface AuthState {
  user: User | null
  // 'idle' before the initial session check has run, 'loading' while it's
  // in flight, 'ready' once we know either way — route guards wait for 'ready'.
  status: 'idle' | 'loading' | 'ready'
  checkAuth: () => Promise<void>
  login: (email: string, password: string) => Promise<AuthResult>
  signup: (name: string, email: string, password: string) => Promise<AuthResult>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: 'idle',

  checkAuth: async () => {
    set({ status: 'loading' })
    try {
      const user = await api.me()
      set({ user, status: 'ready' })
    } catch {
      set({ user: null, status: 'ready' })
    }
  },

  login: async (email, password) => {
    try {
      const user = await api.login(email, password)
      set({ user, status: 'ready' })
      return { ok: true }
    } catch (err) {
      return { ok: false, message: messageOf(err, 'Could not log in. Try again.') }
    }
  },

  signup: async (name, email, password) => {
    try {
      const user = await api.signup(name, email, password)
      set({ user, status: 'ready' })
      return { ok: true }
    } catch (err) {
      return { ok: false, message: messageOf(err, 'Could not sign up. Try again.') }
    }
  },

  logout: async () => {
    try {
      await api.logout()
    } finally {
      set({ user: null })
    }
  },
}))
