import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { GoogleIcon } from '../components/icons'
import { api, ApiRequestError } from '../lib/api'
import { useAuthStore } from '../store/authStore'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Friendly copy for the `?error=` codes the backend's Google OAuth
// redirects can land on /login with (see backend/nota/routes/auth.py).
const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_not_configured: "Google sign-in isn't set up on this server yet.",
  google_auth_failed: "Google sign-in didn't complete — try again or use your password.",
}

function useGoogleAuthError(): string | null {
  const [searchParams, setSearchParams] = useSearchParams()
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    const code = searchParams.get('error')
    const known = code ? GOOGLE_ERROR_MESSAGES[code] : undefined
    if (known) {
      setMessage(known)
      const next = new URLSearchParams(searchParams)
      next.delete('error')
      setSearchParams(next, { replace: true })
    }
    // Only react to the param actually present on mount/navigation; the
    // setSearchParams call above intentionally doesn't re-trigger a message.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return message
}

function AuthShell({ children, swap }: { children: ReactNode; swap: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-bg px-9 py-7">
      <Link
        to="/"
        className="self-start text-[13.5px] text-muted no-underline hover:text-pine"
      >
        ← Back to home
      </Link>
      <div className="rise flex flex-1 flex-col items-center justify-center py-10">
        <div className="mb-7 font-display text-[28px] text-ink">Nota</div>
        <div className="w-90 max-w-full rounded-card border border-line bg-card p-8">
          {children}
        </div>
        <div className="mt-5 text-[13.5px] text-muted">{swap}</div>
      </div>
    </div>
  )
}

interface FieldProps {
  label: string
  type: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  error?: string
  onBlur?: () => void
  hint?: string
  labelRight?: ReactNode
  autoComplete?: string
}

function Field({
  label,
  type,
  placeholder,
  value,
  onChange,
  error,
  onBlur,
  hint,
  labelRight,
  autoComplete,
}: FieldProps) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label className="text-[13px] font-medium text-ink-soft">{label}</label>
        {labelRight}
      </div>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        aria-invalid={!!error}
        className={`nota-input box-border w-full rounded-input border bg-card px-3.5 py-2.75 font-sans text-sm text-ink ${
          error ? 'border-error' : 'border-line-strong'
        }`}
      />
      {error ? (
        <div className="mt-1.25 text-xs text-error">{error}</div>
      ) : (
        hint && <div className="mt-1.25 text-xs text-faint">{hint}</div>
      )}
    </div>
  )
}

function PrimaryButton({ children, disabled }: { children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="w-full cursor-pointer rounded-pill border-none bg-pine py-3.25 font-sans text-[14.5px] font-semibold text-on-pine hover:bg-pine-deep disabled:cursor-default disabled:bg-ghost"
    >
      {children}
    </button>
  )
}

const RESET_CONFIRMATION_MESSAGE =
  'If that email has an account, a reset link is on its way — check your inbox.'

export function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})
  const googleError = useGoogleAuthError()
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [mode, setMode] = useState<'login' | 'forgot'>('login')
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotError, setForgotError] = useState<string | undefined>()
  const [forgotSubmitting, setForgotSubmitting] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)

  const validateEmail = (v: string) =>
    !v.trim() ? 'Enter your email.' : !EMAIL_RE.test(v) ? 'That doesn’t look like an email.' : undefined
  const validatePassword = (v: string) => (!v ? 'Enter your password.' : undefined)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const next = { email: validateEmail(email), password: validatePassword(password) }
    setErrors(next)
    setFormError(null)
    if (next.email || next.password) return
    setSubmitting(true)
    const result = await login(email, password)
    setSubmitting(false)
    if (result.ok) navigate('/dashboard')
    else setFormError(result.message)
  }

  const submitForgot = async (e: React.FormEvent) => {
    e.preventDefault()
    const emailError = validateEmail(forgotEmail)
    setForgotError(emailError)
    if (emailError) return
    setForgotSubmitting(true)
    // The backend always answers 200 here (known or unknown email alike),
    // so a thrown error only means the request itself never landed — the
    // neutral confirmation still applies either way.
    try {
      await api.forgotPassword(forgotEmail)
    } catch {
      // Ignored — fall through to the same neutral confirmation.
    }
    setForgotSubmitting(false)
    setForgotSent(true)
  }

  const backToLogin = (
    <button
      type="button"
      onClick={() => {
        setMode('login')
        setForgotSent(false)
        setForgotEmail('')
        setForgotError(undefined)
      }}
      className="cursor-pointer border-none bg-transparent p-0 font-sans text-[13.5px] text-pine no-underline hover:text-brass"
    >
      Back to login
    </button>
  )

  if (mode === 'forgot') {
    return (
      <AuthShell swap={backToLogin}>
        <div className="font-display text-[23px] text-ink">Reset your password.</div>
        {forgotSent ? (
          <div className="mt-6 text-sm text-ink-soft">{RESET_CONFIRMATION_MESSAGE}</div>
        ) : (
          <form onSubmit={submitForgot} noValidate className="mt-6 flex flex-col gap-4">
            <Field
              label="Email"
              type="email"
              placeholder="you@ensemble.org"
              value={forgotEmail}
              onChange={setForgotEmail}
              onBlur={() => setForgotError(validateEmail(forgotEmail))}
              error={forgotError}
              autoComplete="email"
            />
            <PrimaryButton disabled={forgotSubmitting}>
              {forgotSubmitting ? 'Sending…' : 'Send reset link'}
            </PrimaryButton>
          </form>
        )}
      </AuthShell>
    )
  }

  return (
    <AuthShell
      swap={
        <>
          New to Nota?{' '}
          <Link to="/signup" className="text-pine no-underline hover:text-brass">
            Create an account
          </Link>
        </>
      }
    >
      <div className="font-display text-[23px] text-ink">Welcome back.</div>
      <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-4">
        <Field
          label="Email"
          type="email"
          placeholder="you@ensemble.org"
          value={email}
          onChange={setEmail}
          onBlur={() => setErrors((er) => ({ ...er, email: validateEmail(email) }))}
          error={errors.email}
          autoComplete="email"
        />
        <Field
          label="Password"
          type="password"
          placeholder="••••••••"
          value={password}
          onChange={setPassword}
          onBlur={() => setErrors((er) => ({ ...er, password: validatePassword(password) }))}
          error={errors.password}
          autoComplete="current-password"
          labelRight={
            <button
              type="button"
              onClick={() => setMode('forgot')}
              className="cursor-pointer border-none bg-transparent p-0 font-sans text-xs text-pine no-underline hover:text-brass"
            >
              Forgot?
            </button>
          }
        />
        {(formError || googleError) && (
          <div className="text-xs text-error">{formError || googleError}</div>
        )}
        <div className="mt-1">
          <PrimaryButton disabled={submitting}>{submitting ? 'Logging in…' : 'Log in'}</PrimaryButton>
        </div>
        <div className="flex items-center gap-3 text-xs text-ghost">
          <span className="h-px flex-1 bg-line" />
          or
          <span className="h-px flex-1 bg-line" />
        </div>
        <button
          type="button"
          onClick={() => {
            window.location.href = '/api/auth/google'
          }}
          className="flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-pill border border-line-strong bg-transparent py-3 font-sans text-sm font-medium text-ghost"
        >
          <GoogleIcon />
          Continue with Google
        </button>
      </form>
    </AuthShell>
  )
}

export function Signup() {
  const navigate = useNavigate()
  const signup = useAuthStore((s) => s.signup)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ name?: string; email?: string; password?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const validateName = (v: string) => (!v.trim() ? 'Tell us your name.' : undefined)
  const validateEmail = (v: string) =>
    !v.trim() ? 'Enter your email.' : !EMAIL_RE.test(v) ? 'That doesn’t look like an email.' : undefined
  const validatePassword = (v: string) =>
    v.length < 8 ? 'At least 8 characters.' : undefined

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const next = {
      name: validateName(name),
      email: validateEmail(email),
      password: validatePassword(password),
    }
    setErrors(next)
    setFormError(null)
    if (next.name || next.email || next.password) return
    setSubmitting(true)
    const result = await signup(name, email, password)
    setSubmitting(false)
    if (result.ok) {
      navigate('/dashboard')
      return
    }
    if (result.message.toLowerCase().includes('email')) {
      setErrors((er) => ({ ...er, email: result.message }))
    } else {
      setFormError(result.message)
    }
  }

  return (
    <AuthShell
      swap={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-pine no-underline hover:text-brass">
            Log in
          </Link>
        </>
      }
    >
      <div className="font-display text-[23px] text-ink">Take a seat.</div>
      <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-4">
        <Field
          label="Name"
          type="text"
          placeholder="Jaden Li"
          value={name}
          onChange={setName}
          onBlur={() => setErrors((er) => ({ ...er, name: validateName(name) }))}
          error={errors.name}
          autoComplete="name"
        />
        <Field
          label="Email"
          type="email"
          placeholder="you@ensemble.org"
          value={email}
          onChange={setEmail}
          onBlur={() => setErrors((er) => ({ ...er, email: validateEmail(email) }))}
          error={errors.email}
          autoComplete="email"
        />
        <Field
          label="Password"
          type="password"
          placeholder="••••••••"
          value={password}
          onChange={setPassword}
          onBlur={() => setErrors((er) => ({ ...er, password: validatePassword(password) }))}
          error={errors.password}
          hint="At least 8 characters."
          autoComplete="new-password"
        />
        {formError && <div className="text-xs text-error">{formError}</div>}
        <PrimaryButton disabled={submitting}>{submitting ? 'Creating account…' : 'Create account'}</PrimaryButton>
        <div className="text-center text-xs text-faint">Free to use. No credit card required.</div>
      </form>
    </AuthShell>
  )
}

const INVALID_RESET_TOKEN_MESSAGE = 'That link is invalid or has expired — request a new one.'

const backToLoginLink = (
  <Link to="/login" className="text-pine no-underline hover:text-brass">
    Back to login
  </Link>
)

export function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | undefined>()
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  const validatePassword = (v: string) => (v.length < 8 ? 'At least 8 characters.' : undefined)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const passwordError = validatePassword(password)
    setError(passwordError)
    setFormError(null)
    if (passwordError) return
    setSubmitting(true)
    try {
      await api.resetPassword(token, password)
      setDone(true)
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === 'INVALID_RESET_TOKEN') {
        setFormError(INVALID_RESET_TOKEN_MESSAGE)
      } else {
        setFormError(
          err instanceof ApiRequestError ? err.message : 'Could not reset your password. Try again.',
        )
      }
    }
    setSubmitting(false)
  }

  if (!token) {
    return (
      <AuthShell swap={backToLoginLink}>
        <div className="font-display text-[23px] text-ink">Reset your password.</div>
        <div className="mt-6 text-sm text-error">{INVALID_RESET_TOKEN_MESSAGE}</div>
      </AuthShell>
    )
  }

  if (done) {
    return (
      <AuthShell swap={backToLoginLink}>
        <div className="font-display text-[23px] text-ink">Password updated.</div>
        <div className="mt-6 text-sm text-ink-soft">
          Your password has been reset. You can now log in with your new password.
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell swap={backToLoginLink}>
      <div className="font-display text-[23px] text-ink">Choose a new password.</div>
      <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-4">
        <Field
          label="New password"
          type="password"
          placeholder="••••••••"
          value={password}
          onChange={setPassword}
          onBlur={() => setError(validatePassword(password))}
          error={error}
          hint="At least 8 characters."
          autoComplete="new-password"
        />
        {formError && <div className="text-xs text-error">{formError}</div>}
        <PrimaryButton disabled={submitting}>{submitting ? 'Resetting…' : 'Reset password'}</PrimaryButton>
      </form>
    </AuthShell>
  )
}
