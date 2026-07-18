import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { useScoreStore } from '../store/scoreStore'
import { useThemeStore } from '../store/themeStore'
import { useVerovio, loadScoreData } from '../hooks/useVerovio'
import { useSpeechReadback } from '../hooks/useSpeechReadback'
import { downloadScore } from '../lib/download'
import { api, ApiRequestError } from '../lib/api'
import { VoiceBar, type CommandToast } from '../components/VoiceBar'
import { MoonIcon, PencilIcon, SunIcon } from '../components/icons'

const SCALE = 40
const PAGE_GAP = 24
const AREA_PAD = 96
const SHEET_PAD_X = 112
const BASE_SHEET = 720
const HISTORY_LIMIT = 8

export function Viewer() {
  const { id } = useParams()
  const score = useScoreStore((s) => (id ? s.scores.find((sc) => sc.id === id) : undefined))
  const loadScoreDetail = useScoreStore((s) => s.loadScoreDetail)
  const [notFound, setNotFound] = useState(false)

  // Scores opened via a direct link (or a page refresh) may not be in the
  // in-memory store yet — the dashboard only ever fetches summaries, and a
  // fresh session hasn't fetched anything. Fetch this one score directly
  // rather than bouncing the user back to the dashboard.
  useEffect(() => {
    if (!id || score) return
    let cancelled = false
    loadScoreDetail(id).then((result) => {
      if (!cancelled && !result.ok) setNotFound(true)
    })
    return () => {
      cancelled = true
    }
  }, [id, score, loadScoreDetail])

  if (!id || notFound) return <Navigate to="/dashboard" replace />
  if (!score) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg font-mono text-[12.5px] text-ghost">
        loading score…
      </div>
    )
  }
  return <ViewerInner key={score.id} scoreId={score.id} />
}

function ViewerInner({ scoreId }: { scoreId: string }) {
  const score = useScoreStore((s) => s.scores.find((sc) => sc.id === scoreId))!
  const updateScore = useScoreStore((s) => s.updateScore)
  const renameScore = useScoreStore((s) => s.renameScore)
  const loadScoreDetail = useScoreStore((s) => s.loadScoreDetail)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const { toolkit, isLoading, error } = useVerovio()
  const { speak, cancel: cancelSpeech, speaking: ttsSpeaking } = useSpeechReadback()

  const [currentPage, setCurrentPage] = useState(() =>
    Math.max(1, Math.min(score.lastPage, score.totalPages ?? score.lastPage)),
  )
  const totalPages = score.totalPages ?? 1
  const [zoom, setZoom] = useState(100)
  const [areaWidth, setAreaWidth] = useState(0)
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState(score.title)

  const [detailLoading, setDetailLoading] = useState(score.data === undefined)
  const [detailError, setDetailError] = useState<string | null>(null)

  const [commandBusy, setCommandBusy] = useState(false)
  const [toast, setToast] = useState<CommandToast | null>(null)
  const [clarification, setClarification] = useState<string | null>(null)
  const [highlightIds, setHighlightIds] = useState<string[]>([])
  const [history, setHistory] = useState<string[]>([])
  const [voiceRearmToken, setVoiceRearmToken] = useState(0)
  const [voiceStandDownToken, setVoiceStandDownToken] = useState(0)
  // Counts consecutive needs_clarification responses so the mic only
  // re-arms itself once in a row — a second ambiguous answer in a row hands
  // control back to the typed input rather than looping forever.
  const clarificationStreakRef = useRef(0)

  const leftRef = useRef<HTMLDivElement>(null)
  const rightRef = useRef<HTMLDivElement>(null)
  const observerRef = useRef<ResizeObserver | null>(null)
  const highlightTimeoutRef = useRef<number | null>(null)
  const highlightAttemptedPageRef = useRef<number | null>(null)
  const toastTimeoutRef = useRef<number | null>(null)

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

  // Fetch the full MusicXML the first time this score is opened — the
  // dashboard's list view only carries summary fields.
  useEffect(() => {
    if (score.data !== undefined) {
      setDetailLoading(false)
      return
    }
    let cancelled = false
    setDetailLoading(true)
    setDetailError(null)
    loadScoreDetail(scoreId).then((result) => {
      if (cancelled) return
      setDetailLoading(false)
      if (!result.ok) setDetailError(result.message)
    })
    return () => {
      cancelled = true
    }
  }, [scoreId, score.data, loadScoreDetail])

  // Pull command history for the chips row; if the endpoint isn't live yet
  // (or the score has no history) this just leaves the chips empty.
  useEffect(() => {
    let cancelled = false
    api
      .getHistory(scoreId)
      .then((res) => {
        if (cancelled) return
        setHistory(
          res.items
            .map((it) => it.confirmation || it.transcript)
            .filter(Boolean)
            .slice(-HISTORY_LIMIT),
        )
      })
      .catch(() => {
        // History chips are a nice-to-have; leave them empty on failure.
      })
    return () => {
      cancelled = true
    }
  }, [scoreId])

  useEffect(() => {
    if (!toast) return
    if (toastTimeoutRef.current) window.clearTimeout(toastTimeoutRef.current)
    toastTimeoutRef.current = window.setTimeout(() => setToast(null), 4000)
    return () => {
      if (toastTimeoutRef.current) window.clearTimeout(toastTimeoutRef.current)
    }
  }, [toast])

  useEffect(
    () => () => {
      if (highlightTimeoutRef.current) window.clearTimeout(highlightTimeoutRef.current)
    },
    [],
  )

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

    // Highlight elements changed by the most recent command. The ids are
    // only valid for the MusicXML just rendered — see clearHighlights().
    if (highlightIds.length > 0) {
      const found = highlightIds
        .map((elId) => document.getElementById(elId))
        .filter((el): el is HTMLElement => el !== null)

      if (found.length > 0) {
        if (highlightTimeoutRef.current) window.clearTimeout(highlightTimeoutRef.current)
        found.forEach((el) => el.classList.add('nota-highlight'))
        highlightAttemptedPageRef.current = null
        const idsToClear = highlightIds
        highlightTimeoutRef.current = window.setTimeout(() => {
          found.forEach((el) => el.classList.remove('nota-highlight'))
          setHighlightIds((current) => (current === idsToClear ? [] : current))
        }, 3000)
      } else if (highlightAttemptedPageRef.current !== page) {
        // None of the changed ids are on the currently rendered page(s).
        // Try to jump to the page that contains the first one; if Verovio
        // can't locate it either, give up gracefully (no highlight).
        highlightAttemptedPageRef.current = page
        try {
          const targetPage = toolkit.getPageWithElement(highlightIds[0])
          if (targetPage && targetPage >= 1 && targetPage !== page) {
            setCurrentPage(targetPage)
          } else {
            setHighlightIds([])
          }
        } catch {
          setHighlightIds([])
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    toolkit,
    hasData,
    score.data,
    score.format,
    score.totalPages,
    currentPage,
    sheetWidth,
    pagesShown,
    scoreId,
    updateScore,
    highlightIds,
  ])

  const clearHighlights = useCallback(() => {
    if (highlightTimeoutRef.current) {
      window.clearTimeout(highlightTimeoutRef.current)
      highlightTimeoutRef.current = null
    }
    document.querySelectorAll('.nota-highlight').forEach((el) => el.classList.remove('nota-highlight'))
    highlightAttemptedPageRef.current = null
    setHighlightIds([])
  }, [])

  const handleSubmitCommand = useCallback(
    async (text: string) => {
      if (commandBusy) return
      clearHighlights()
      setClarification(null)
      setCommandBusy(true)
      // A new command is about to start (and may re-arm the mic); don't let
      // a reply from the previous one keep talking over it.
      cancelSpeech()
      try {
        const result = await api.sendCommand(scoreId, text)
        updateScore(scoreId, { data: result.musicxml, format: 'xml', modifiedAt: Date.now(), lastSaid: text })
        setHighlightIds(result.changed_element_ids)

        if (result.needs_clarification) {
          clarificationStreakRef.current += 1
          setClarification(result.confirmation)
          setToast(null)
          // First clarification in a row: re-arm the mic so the musician
          // can answer hands-free — but only once Nota is done asking, so
          // the mic doesn't end up recording its own voice. A second
          // clarification in a row: stop guessing, no need to wait on
          // speech for that since it just cuts the mic and hands off to text.
          const shouldRearm = clarificationStreakRef.current <= 1
          speak(result.confirmation, () => {
            if (shouldRearm) setVoiceRearmToken((t) => t + 1)
          })
          if (!shouldRearm) {
            setVoiceStandDownToken((t) => t + 1)
          }
        } else {
          clarificationStreakRef.current = 0
          setClarification(null)
          if (result.confirmation) {
            setToast({ kind: 'confirmation', text: result.confirmation })
            setHistory((h) => [...h, result.confirmation].slice(-HISTORY_LIMIT))
            speak(result.confirmation)
          } else {
            setToast(null)
          }
        }
      } catch (err) {
        clarificationStreakRef.current = 0
        if (err instanceof ApiRequestError && err.code === 'COMMAND_IN_PROGRESS') {
          setToast({ kind: 'notice', text: 'Still working on the last command…' })
        } else if (err instanceof ApiRequestError && err.code === 'EMPTY_TRANSCRIPT') {
          setToast({ kind: 'notice', text: 'Didn’t catch that — try again.' })
        } else {
          setToast({
            kind: 'error',
            text: err instanceof Error ? err.message : 'That command failed.',
          })
        }
      } finally {
        setCommandBusy(false)
      }
    },
    [commandBusy, clearHighlights, scoreId, updateScore, cancelSpeech, speak],
  )

  const handleUndo = useCallback(async () => {
    clearHighlights()
    try {
      const result = await api.undo(scoreId)
      updateScore(scoreId, { data: result.musicxml, format: 'xml', modifiedAt: Date.now() })
      setToast(result.summary ? { kind: 'notice', text: result.summary } : null)
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === 'NOTHING_TO_UNDO') {
        setToast({ kind: 'notice', text: 'Nothing to undo.' })
      } else {
        setToast({ kind: 'error', text: err instanceof Error ? err.message : 'Undo failed.' })
      }
    }
  }, [clearHighlights, scoreId, updateScore])

  const handleRedo = useCallback(async () => {
    clearHighlights()
    try {
      const result = await api.redo(scoreId)
      updateScore(scoreId, { data: result.musicxml, format: 'xml', modifiedAt: Date.now() })
      setToast(result.summary ? { kind: 'notice', text: result.summary } : null)
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === 'NOTHING_TO_REDO') {
        setToast({ kind: 'notice', text: 'Nothing to redo.' })
      } else {
        setToast({ kind: 'error', text: err instanceof Error ? err.message : 'Redo failed.' })
      }
    }
  }, [clearHighlights, scoreId, updateScore])

  const commitRename = () => {
    const title = draftTitle.trim()
    if (title && title !== score.title) void renameScore(scoreId, title)
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
          <span className="font-mono text-[11.5px] text-faint">{score.marks} measures</span>
          <button
            onClick={() => downloadScore(scoreId, `${score.title}.musicxml`)}
            className="cursor-pointer whitespace-nowrap rounded-pill border border-line-strong bg-transparent px-4 py-1.75 font-sans text-[13px] font-medium text-ink hover:border-pine hover:text-pine"
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
            <div className="self-center font-mono text-[12.5px] text-ghost">
              {detailLoading ? 'loading score…' : detailError ? (
                <span className="text-error">{detailError}</span>
              ) : (
                'no score data yet'
              )}
            </div>
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

      <VoiceBar
        history={history}
        busy={commandBusy}
        toast={toast}
        clarification={clarification}
        onSubmitCommand={(text) => void handleSubmitCommand(text)}
        onUndo={() => void handleUndo()}
        onRedo={() => void handleRedo()}
        onVoiceMessage={(t) => setToast(t)}
        voiceRearmToken={voiceRearmToken}
        voiceStandDownToken={voiceStandDownToken}
        onManualRecordStart={cancelSpeech}
        ttsSpeaking={ttsSpeaking}
      />
    </div>
  )
}
