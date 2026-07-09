import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { useScoreStore } from '../store/scoreStore'
import { useThemeStore } from '../store/themeStore'
import { useVerovio, loadScoreData } from '../hooks/useVerovio'
import { downloadScore } from '../lib/download'
import { VoiceBar } from '../components/VoiceBar'
import { MoonIcon, PencilIcon, SunIcon } from '../components/icons'

const SCALE = 40
const PAGE_GAP = 24
const AREA_PAD = 96
const SHEET_PAD_X = 112
const BASE_SHEET = 720

export function Viewer() {
  const { id } = useParams()
  const score = useScoreStore((s) => s.scores.find((sc) => sc.id === id))

  if (!score) return <Navigate to="/dashboard" replace />
  return <ViewerInner key={score.id} scoreId={score.id} />
}

function ViewerInner({ scoreId }: { scoreId: string }) {
  const score = useScoreStore((s) => s.scores.find((sc) => sc.id === scoreId))!
  const updateScore = useScoreStore((s) => s.updateScore)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const { toolkit, isLoading, error } = useVerovio()

  const [currentPage, setCurrentPage] = useState(() =>
    Math.max(1, Math.min(score.lastPage, score.totalPages ?? score.lastPage)),
  )
  const totalPages = score.totalPages ?? 1
  const [zoom, setZoom] = useState(100)
  const [areaWidth, setAreaWidth] = useState(0)
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState(score.title)

  const leftRef = useRef<HTMLDivElement>(null)
  const rightRef = useRef<HTMLDivElement>(null)
  const observerRef = useRef<ResizeObserver | null>(null)

  const areaRef = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect()
    observerRef.current = null
    if (node) {
      const observer = new ResizeObserver((entries) => {
        setAreaWidth(entries[0].contentRect.width)
      })
      observer.observe(node)
      observerRef.current = observer
    }
  }, [])

  const hasData = score.data !== undefined
  const pagesShown = hasData && areaWidth >= 1100 && totalPages > 1 ? 2 : 1
  const fitWidth =
    pagesShown === 2
      ? Math.floor((areaWidth - AREA_PAD - PAGE_GAP) / 2)
      : Math.min(BASE_SHEET, Math.max(320, areaWidth - AREA_PAD))
  const sheetWidth = Math.round(Math.min(BASE_SHEET, fitWidth) * (zoom / 100))

  useEffect(() => {
    updateScore(scoreId, { lastPage: currentPage })
  }, [scoreId, currentPage, updateScore])

  useEffect(() => {
    if (!toolkit || !hasData || !leftRef.current || sheetWidth === 0) return
    const innerWidth = sheetWidth - SHEET_PAD_X
    toolkit.setOptions({
      pageWidth: Math.floor(innerWidth * (100 / SCALE)),
      scale: SCALE,
      adjustPageHeight: true,
      footer: 'none' as const,
    })
    if (!loadScoreData(toolkit, score.data!, score.format ?? 'xml')) return
    const pageCount = toolkit.getPageCount()
    if (pageCount !== score.totalPages) updateScore(scoreId, { totalPages: pageCount })
    const page = Math.min(currentPage, pageCount)

    leftRef.current.innerHTML = toolkit.renderToSVG(page)
    if (rightRef.current) {
      const next = page + 1
      if (pagesShown === 2 && next <= pageCount) {
        rightRef.current.innerHTML = toolkit.renderToSVG(next)
        rightRef.current.parentElement!.style.display = ''
      } else {
        rightRef.current.innerHTML = ''
        rightRef.current.parentElement!.style.display = 'none'
      }
    }
  }, [toolkit, hasData, score.data, score.format, score.totalPages, currentPage, sheetWidth, pagesShown, scoreId, updateScore])

  const commitRename = () => {
    const title = draftTitle.trim()
    if (title && title !== score.title) updateScore(scoreId, { title, modifiedAt: Date.now() })
    else setDraftTitle(score.title)
    setRenaming(false)
  }

  const lastShown = Math.min(currentPage + pagesShown - 1, totalPages)
  const pagerLabel =
    pagesShown === 2 && lastShown > currentPage
      ? `pages ${currentPage}–${lastShown} / ${totalPages}`
      : `page ${currentPage} / ${totalPages}`

  return (
    <div className="flex h-screen flex-col bg-bg">
      <div className="flex items-center justify-between border-b border-line bg-bg px-7 py-3.5">
        <div className="flex flex-1 items-center gap-5">
          <Link
            to="/dashboard"
            className="whitespace-nowrap text-[13.5px] text-muted no-underline hover:text-pine"
          >
            ← Library
          </Link>
        </div>
        <div className="flex items-baseline gap-2.5">
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
              className="nota-input rounded-input border border-line-strong bg-card px-2 py-0.5 text-center font-display text-[19px] text-ink"
            />
          ) : (
            <>
              <span className="whitespace-nowrap font-display text-[19px] text-ink">
                {score.title}
              </span>
              <button
                aria-label="Rename score"
                onClick={() => {
                  setDraftTitle(score.title)
                  setRenaming(true)
                }}
                className="cursor-pointer border-none bg-transparent p-1 text-faint hover:text-ink"
              >
                <PencilIcon />
              </button>
            </>
          )}
        </div>
        <div className="flex flex-1 items-center justify-end gap-3.5">
          <span className="font-mono text-[11.5px] text-faint">{score.marks} marks</span>
          <button
            onClick={() => downloadScore(score)}
            disabled={!hasData}
            className="cursor-pointer whitespace-nowrap rounded-pill border border-line-strong bg-transparent px-4 py-1.75 font-sans text-[13px] font-medium text-ink hover:border-pine hover:text-pine disabled:cursor-default disabled:text-ghost disabled:hover:border-line-strong"
          >
            Export MusicXML
          </button>
          <button
            aria-label={theme === 'light' ? 'Switch to night mode' : 'Switch to light mode'}
            onClick={toggleTheme}
            className={`cursor-pointer border-none bg-transparent p-1 ${
              theme === 'light' ? 'text-muted hover:text-ink' : 'text-brass'
            }`}
          >
            {theme === 'light' ? <MoonIcon /> : <SunIcon />}
          </button>
        </div>
      </div>

      <div ref={areaRef} className="relative flex-1 overflow-auto">
        <div className="flex min-h-full items-start justify-center gap-6 px-6 py-9">
          {!hasData ? (
            <DemoSheet width={sheetWidth} title={score.title} composer={score.composer} />
          ) : error ? (
            <div className="self-center text-sm text-error">Failed to load Verovio: {error}</div>
          ) : isLoading ? (
            <div className="self-center font-mono text-[12.5px] text-ghost">
              warming up the engraver…
            </div>
          ) : (
            <>
              <div
                className="shrink-0 border border-line-faint bg-card px-14 py-13 shadow-sheet"
                style={{ width: sheetWidth }}
              >
                <div ref={leftRef} className="score-svg" />
              </div>
              <div
                className="shrink-0 border border-line-faint bg-card px-14 py-13 shadow-sheet"
                style={{ width: sheetWidth }}
              >
                <div ref={rightRef} className="score-svg" />
              </div>
            </>
          )}
        </div>

        {totalPages > 1 && (
          <div className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-3.5 rounded-pill border border-line bg-card px-4 py-1.75 text-[13px] text-muted">
            <button
              aria-label="Previous page"
              onClick={() => setCurrentPage((p) => Math.max(1, p - pagesShown))}
              disabled={currentPage <= 1}
              className="cursor-pointer border-none bg-transparent p-0 px-1 text-[15px] text-ink disabled:cursor-default disabled:text-ghost"
            >
              ‹
            </button>
            <span className="font-mono text-xs">{pagerLabel}</span>
            <button
              aria-label="Next page"
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + pagesShown))}
              disabled={lastShown >= totalPages}
              className="cursor-pointer border-none bg-transparent p-0 px-1 text-[15px] text-ink disabled:cursor-default disabled:text-ghost"
            >
              ›
            </button>
          </div>
        )}

        <div className="absolute bottom-5 right-6 flex flex-col overflow-hidden rounded-pill border border-line bg-card">
          <button
            aria-label="Zoom in"
            onClick={() => setZoom((z) => Math.min(200, z + 10))}
            className="cursor-pointer border-none bg-transparent px-3 py-2.25 text-[15px] leading-none text-ink hover:bg-mist"
          >
            +
          </button>
          <button
            aria-label="Zoom out"
            onClick={() => setZoom((z) => Math.max(50, z - 10))}
            className="cursor-pointer border-0 border-t border-solid border-line-faint bg-transparent px-3 py-2.25 text-[15px] leading-none text-ink hover:bg-mist"
          >
            −
          </button>
        </div>
      </div>

      <VoiceBar />
    </div>
  )
}

function DemoSheet({ width, title, composer }: { width: number; title: string; composer?: string }) {
  return (
    <div
      className="flex shrink-0 flex-col gap-11 border border-line-faint bg-card px-14 py-13 shadow-sheet"
      style={{ width }}
    >
      <div className="text-center">
        <div className="font-display text-[22px] text-ink">{title}</div>
        {composer && (
          <div className="mt-1 font-mono text-[11px] text-ghost">{composer}</div>
        )}
      </div>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="staff-lines h-6.5!" />
      ))}
      <div className="text-center font-mono text-[10px] text-ghost">
        demo score — upload a MusicXML file to see a live verovio render
      </div>
    </div>
  )
}
