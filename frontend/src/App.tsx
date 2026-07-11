import { useEffect, type ReactNode } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Landing } from './pages/Landing'
import { Login, Signup } from './pages/Auth'
import { Dashboard } from './pages/Dashboard'
import { Viewer } from './pages/Viewer'
import { useAuthStore } from './store/authStore'

function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status)
  const user = useAuthStore((s) => s.user)
  const checkAuth = useAuthStore((s) => s.checkAuth)

  useEffect(() => {
    if (status === 'idle') void checkAuth()
  }, [status, checkAuth])

  if (status !== 'ready') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg font-mono text-[12.5px] text-ghost">
        loading…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/score/:id"
        element={
          <RequireAuth>
            <Viewer />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
