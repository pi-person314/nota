import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useScoreStore, type ShelfTab } from '../store/scoreStore'
import { useAuthStore } from '../store/authStore'
import { useThemeStore } from '../store/themeStore'
import { ListeningPill } from './ListeningPill'

const TABS: { id: ShelfTab; label: string }[] = [
  { id: 'library', label: 'Library' },
  { id: 'recent', label: 'Recent' },
  { id: 'starred', label: 'Starred' },
]

export function Navbar() {
  const tab = useScoreStore((s) => s.tab)
  const setTab = useScoreStore((s) => s.setTab)
  const resetScores = useScoreStore((s) => s.reset)
  const userName = useAuthStore((s) => s.user?.name ?? '')
  const logout = useAuthStore((s) => s.logout)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!menuOpen) return
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [menuOpen])

  return (
    <header className="flex items-center justify-between border-b border-line bg-bg px-12 py-5 max-md:px-6">
      <div className="flex items-baseline gap-10">
        <Link to="/dashboard" className="font-display text-2xl text-ink no-underline">
          Nota
        </Link>
        <nav className="flex gap-7 text-sm font-medium max-md:hidden">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`cursor-pointer border-none bg-transparent p-0 pb-0.5 font-sans text-sm font-medium ${
                tab === t.id
                  ? 'border-b-2 border-solid border-b-pine text-ink'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <ListeningPill />
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="flex h-8.5 w-8.5 cursor-pointer items-center justify-center rounded-full border-none bg-pine text-[13px] font-semibold text-on-pine"
          >
            {userName.charAt(0).toUpperCase()}
          </button>
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-11 z-20 w-44 rounded-card border border-line bg-card py-1.5 shadow-bloom"
            >
              <MenuItem label="Settings" onClick={() => setMenuOpen(false)} />
              <MenuItem
                label={theme === 'light' ? 'Night mode' : 'Light mode'}
                onClick={() => {
                  toggleTheme()
                  setMenuOpen(false)
                }}
              />
              <div className="mx-4 my-1 h-px bg-line-faint" />
              <MenuItem
                label="Log out"
                onClick={() => {
                  setMenuOpen(false)
                  void logout().then(() => {
                    resetScores()
                    navigate('/')
                  })
                }}
              />
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

function MenuItem({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className="block w-full cursor-pointer border-none bg-transparent px-4 py-2 text-left font-sans text-[13.5px] text-ink hover:bg-mist"
    >
      {label}
    </button>
  )
}
