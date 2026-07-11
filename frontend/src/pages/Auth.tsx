import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { GoogleIcon } from '../components/icons'
import { useAuthStore } from '../store/authStore'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

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

export function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

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
            <a href="#" className="text-xs text-pine no-underline hover:text-brass">
              Forgot?
            </a>
          }
        />
        {formError && <div className="text-xs text-error">{formError}</div>}
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
          disabled
          title="Google sign-in is coming soon"
          className="flex w-full cursor-default items-center justify-center gap-2.5 rounded-pill border border-line-strong bg-transparent py-3 font-sans text-sm font-medium text-ghost"
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
