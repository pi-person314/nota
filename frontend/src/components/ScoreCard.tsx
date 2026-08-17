import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useScoreStore, scoreMeta, type Score } from '../store/scoreStore'
import { relativeTime } from '../lib/time'
import { downloadScore } from '../lib/download'
import { Thumbnail } from './Thumbnail'
import { ConfirmDialog } from './ConfirmDialog'

export function ScoreCard({ score, delay = 0 }: { score: Score; delay?: number }) {
  const toggleStar = useScoreStore((s) => s.toggleStar)
  const toggleArchive = useScoreStore((s) => s.toggleArchive)
  const renameScore = useScoreStore((s) => s.renameScore)
  const removeScore = useScoreStore((s) => s.removeScore)
  const markOpened = useScoreStore((s) => s.markOpened)
  const navigate = useNavigate()

  const [menuOpen, setMenuOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState(score.title)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [menuOpen])

  if (score.pending) {
    return (
      <div className="skeleton-pulse rise overflow-hidden rounded-card border border-line bg-card" style={{ animationDelay: `${delay}ms` }}>
        <div className="h-32 border-b border-line-faint bg-mist" />
        <div className="p-5">
          <div className="h-4 w-2/3 rounded-input bg-mist" />
          <div className="mt-2.5 h-3 w-1/2 rounded-input bg-mist" />
        </div>
      </div>
    )
  }

  const commitRename = () => {
    const title = draftTitle.trim()
    if (title && title !== score.title) {
      void renameScore(score.id, title)
    } else {
      setDraftTitle(score.title)
    }
    setRenaming(false)
  }

  const open = () => {
    if (renaming) return
    markOpened(score.id)
    navigate(`/score/${score.id}`)
  }

  return (
    <div
      className="rise group cursor-pointer rounded-card border border-line bg-card transition-shadow hover:shadow-bloom"
      style={{ animationDelay: `${delay}ms` }}
      onClick={open}
      role="link"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') open()
      }}
    >
      <Thumbnail
        svg={score.thumbnail}
        caption="preview unavailable"
        className="h-32 gap-3 overflow-hidden rounded-t-card border-b border-line-faint px-5 py-4.5"
      />
      <div className="px-5 pb-4 pt-3.5">
        <div className="flex items-start justify-between gap-2.5">
          {renaming ? (
            <input
              autoFocus
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename()
                if (e.key === 'Escape') {
                  setDraftTitle(score.title)
                  setRenaming(false)
                }
              }}
              onClick={(e) => e.stopPropagation()}
              className="nota-input w-full rounded-input border border-line-strong bg-card font-display text-[17px] leading-tight text-ink"
            />
          ) : (
            <div className="font-display text-[17px] leading-tight text-ink">{score.title}</div>
          )}
          <div className="flex items-center gap-1.5">
            <div className="relative" ref={menuRef}>
              <button
                aria-label={`Actions for ${score.title}`}
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen((o) => !o)
                }}
                className={`cursor-pointer border-none bg-transparent p-0 px-1 text-[15px] leading-none text-faint transition-opacity hover:text-ink ${
                  menuOpen ? '' : 'opacity-0 group-hover:opacity-100'
                }`}
              >
                ⋯
              </button>
              {menuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-6 z-20 w-48 rounded-card border border-line bg-card py-1.5 shadow-bloom"
                  onClick={(e) => e.stopPropagation()}
                >
                  <CardMenuItem
                    label="Rename"
                    onClick={() => {
                      setMenuOpen(false)
                      setDraftTitle(score.title)
                      setRenaming(true)
                    }}
                  />
                  <CardMenuItem
                    label="Download MusicXML"
                    onClick={() => {
                      setMenuOpen(false)
                      downloadScore(score.id, `${score.title}.musicxml`)
                    }}
                  />
                  <CardMenuItem
                    label={score.archived ? 'Unarchive' : 'Archive'}
                    onClick={() => {
                      setMenuOpen(false)
                      void toggleArchive(score.id)
                    }}
                  />
                  <div className="mx-4 my-1 h-px bg-line-faint" />
                  <CardMenuItem
                    label="Delete"
                    onClick={() => {
                      setMenuOpen(false)
                      setConfirming(true)
                    }}
                  />
                </div>
              )}
            </div>
            <button
              aria-label={score.starred ? 'Unstar' : 'Star'}
              aria-pressed={score.starred}
              onClick={(e) => {
                e.stopPropagation()
                void toggleStar(score.id)
              }}
              className={`cursor-pointer border-none bg-transparent p-0 text-[15px] leading-none ${
                score.starred ? 'text-brass' : 'text-line-strong hover:text-ghost'
              }`}
            >
              ★
            </button>
          </div>
        </div>
        <div className="mt-1.5 flex items-baseline justify-between">
          <div className="text-[12.5px] text-faint">
            {scoreMeta(score, relativeTime(score.openedAt))}
          </div>
          <div className="flex items-center gap-1.5">
            {score.fromPdf && (
              <span
                title="Converted from a PDF — recognition is not 100% reliable, so check this score against the original."
                className="rounded-pill border border-line px-1.5 font-mono text-[10px] text-brass"
              >
                PDF
              </span>
            )}
            <div className="font-mono text-[11px] text-ghost">{score.marks} measures</div>
          </div>
        </div>
      </div>
      {confirming && (
        <ConfirmDialog
          title={`Delete “${score.title}”?`}
          body="This takes it off your stand for good. Marks and the file go with it."
          confirmLabel="Delete"
          onConfirm={() => void removeScore(score.id)}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  )
}

function CardMenuItem({
  label,
  onClick,
  disabled = false,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className="block w-full cursor-pointer border-none bg-transparent px-4 py-2 text-left font-sans text-[13.5px] text-ink hover:bg-mist disabled:cursor-default disabled:text-ghost disabled:hover:bg-transparent"
    >
      {label}
    </button>
  )
}
