import { type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useScoreStore } from '../store/scoreStore'
import { useThemeStore, type Theme } from '../store/themeStore'
import { useReadbackStore } from '../store/readbackStore'
import { useWakeWordStore } from '../store/wakeWordStore'

function SettingsCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-card p-6">
      <h2 className="m-0 font-display text-[19px] font-normal text-ink">{title}</h2>
      <div className="mt-4 flex flex-col gap-4">{children}</div>
    </section>
  )
}

interface ToggleRowProps {
  label: string
  description: string
  on: boolean
  onToggle: () => void
  footnote?: string
}

function ToggleRow({ label, description, on, onToggle, footnote }: ToggleRowProps) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <div className="text-[14.5px] font-medium text-ink">{label}</div>
        <div className="mt-0.5 text-[13px] text-muted">{description}</div>
        {footnote && <div className="mt-1.5 text-xs text-faint">{footnote}</div>}
      </div>
      <button
        role="switch"
        aria-checked={on}
        aria-pressed={on}
        onClick={onToggle}
        className={`relative h-6.5 w-11.5 shrink-0 cursor-pointer rounded-pill border-none transition-colors ${
          on ? 'bg-pine' : 'bg-ghost'
        }`}
      >
        <span
          className={`absolute left-0 top-0.75 h-5 w-5 rounded-full bg-on-pine transition-transform ${
            on ? 'translate-x-5.75' : 'translate-x-0.75'
          }`}
        />
      </button>
    </div>
  )
}

function ThemeControl() {
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)

  const options: { id: Theme; label: string }[] = [
    { id: 'light', label: 'Light' },
    { id: 'dark', label: 'Dark' },
  ]

  return (
    <div className="flex items-center justify-between gap-6">
      <div>
        <div className="text-[14.5px] font-medium text-ink">Theme</div>
        <div className="mt-0.5 text-[13px] text-muted">Choose how Nota looks on this device.</div>
      </div>
      <div role="radiogroup" aria-label="Theme" className="flex rounded-pill border border-line p-0.5">
        {options.map((opt) => (
          <button
            key={opt.id}
            role="radio"
            aria-checked={theme === opt.id}
            onClick={() => {
              if (theme !== opt.id) toggleTheme()
            }}
            className={`min-h-8 cursor-pointer whitespace-nowrap rounded-pill border-none px-4 py-1.5 font-sans text-[13px] font-medium ${
              theme === opt.id ? 'bg-pine text-on-pine' : 'bg-transparent text-muted hover:text-pine'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Settings() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const resetScores = useScoreStore((s) => s.reset)
  const muted = useReadbackStore((s) => s.muted)
  const toggleMuted = useReadbackStore((s) => s.toggleMuted)
  const wakeWordArmed = useWakeWordStore((s) => s.armed)
  const toggleWakeWordArmed = useWakeWordStore((s) => s.toggleArmed)

  const handleLogout = () => {
    void logout().then(() => {
      resetScores()
      navigate('/')
    })
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg px-9 py-7">
      <Link to="/dashboard" className="self-start text-[13.5px] text-muted no-underline hover:text-pine">
        ← Back
      </Link>
      <main className="rise mx-auto w-full max-w-2xl flex-1 pb-16 pt-8">
        <h1 className="m-0 font-display text-[32px] font-normal text-ink">Settings</h1>

        <div className="mt-8 flex flex-col gap-5">
          <SettingsCard title="Appearance">
            <ThemeControl />
          </SettingsCard>

          <SettingsCard title="Voice">
            <ToggleRow
              label="Spoken replies"
              description="Nota reads confirmations and questions aloud."
              on={!muted}
              onToggle={toggleMuted}
            />
            <div className="h-px bg-line-faint" />
            <ToggleRow
              label="“Hey Nota” wake word"
              description="Hands-free listening for the wake phrase."
              on={wakeWordArmed}
              onToggle={toggleWakeWordArmed}
            />
          </SettingsCard>

          <SettingsCard title="Account">
            <div>
              <div className="text-[14.5px] font-medium text-ink">{user?.name}</div>
              <div className="mt-0.5 text-[13px] text-muted">{user?.email}</div>
            </div>
            <div>
              <button
                onClick={handleLogout}
                className="min-h-10 cursor-pointer whitespace-nowrap rounded-pill border border-line bg-transparent px-4.5 py-2 font-sans text-[13.5px] font-medium text-error hover:border-error"
              >
                Log out
              </button>
            </div>
          </SettingsCard>
        </div>
      </main>
    </div>
  )
}
