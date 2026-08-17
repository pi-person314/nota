import { useEffect, useMemo } from 'react'
import { useScoreStore, type Score, type SortMode, type ShelfTab } from '../store/scoreStore'
import { useAuthStore } from '../store/authStore'
import { timeOfDayGreeting, countWord } from '../lib/time'
import { Navbar } from '../components/Navbar'
import { ContinueCard } from '../components/ContinueCard'
import { UploadDropzone } from '../components/UploadDropzone'
import { ScoreCard } from '../components/ScoreCard'

function sortScores(scores: Score[], mode: SortMode): Score[] {
  const sorted = [...scores]
  if (mode === 'Last opened') sorted.sort((a, b) => b.openedAt - a.openedAt)
  if (mode === 'Last modified') sorted.sort((a, b) => b.modifiedAt - a.modifiedAt)
  if (mode === 'Name A–Z') sorted.sort((a, b) => a.title.localeCompare(b.title))
  return sorted
}

function emptyLine(tab: ShelfTab, search: string): string {
  if (search) return `Nothing matches “${search}”.`
  if (tab === 'starred') return 'Nothing starred yet — tap a star on any score.'
  if (tab === 'archived') return 'Nothing archived — use a score’s ⋯ menu to tuck it away.'
  return 'Nothing here yet.'
}

export function Dashboard() {
  const scores = useScoreStore((s) => s.scores)
  const search = useScoreStore((s) => s.search)
  const setSearch = useScoreStore((s) => s.setSearch)
  const sortMode = useScoreStore((s) => s.sortMode)
  const cycleSort = useScoreStore((s) => s.cycleSort)
  const tab = useScoreStore((s) => s.tab)
  const fetchScores = useScoreStore((s) => s.fetchScores)
  const loading = useScoreStore((s) => s.loading)
  const loadError = useScoreStore((s) => s.loadError)
  const userName = useAuthStore((s) => s.user?.name ?? '')

  useEffect(() => {
    void fetchScores()
  }, [fetchScores])

  const activeScores = useMemo(() => scores.filter((s) => !s.archived), [scores])

  const lastOpened = useMemo(
    () =>
      activeScores.length
        ? [...activeScores].sort((a, b) => b.openedAt - a.openedAt)[0]
        : undefined,
    [activeScores],
  )

  const shelf = useMemo(() => {
    let list = tab === 'archived' ? scores.filter((s) => s.archived) : activeScores
    if (tab === 'starred') list = list.filter((s) => s.starred)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (s) =>
          s.title.toLowerCase().includes(q) || (s.composer ?? '').toLowerCase().includes(q),
      )
    }
    return sortScores(list, tab === 'recent' ? 'Last opened' : sortMode)
  }, [scores, activeScores, tab, search, sortMode])

  // Any score at all — archived included — keeps the tabbed shelf visible,
  // so a fully-archived library is still reachable via the Archived tab
  // instead of collapsing into the first-run empty state.
  const hasScores = scores.length > 0
  const lastIn = lastOpened ? (lastOpened.composer ?? lastOpened.title) : ''

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <Navbar />
      <main className="rise mx-auto w-full max-w-310 flex-1 px-12 pb-16 pt-11 max-md:px-6">
        <h1 className="m-0 font-display text-[40px] font-normal leading-tight text-ink">
          {timeOfDayGreeting()}, {userName}.
        </h1>
        {activeScores.length > 0 && (
          <p className="mt-2 text-[15px] text-muted">
            {countWord(activeScores.length)} {activeScores.length === 1 ? 'score' : 'scores'} on your stand.
            {lastIn && ` You were last in the ${lastIn}.`}
          </p>
        )}
        {loadError && <p className="mt-2 text-sm text-error">{loadError}</p>}

        {loading && !hasScores ? (
          <div className="mt-10 py-12 text-center font-mono text-[12.5px] text-ghost">
            loading your scores…
          </div>
        ) : !hasScores ? (
          <div className="mt-10">
            <UploadDropzone large headline="Nothing on your stand yet." />
          </div>
        ) : (
          <>
            <div className="mt-7 grid grid-cols-[1.6fr_1fr] gap-5 max-lg:grid-cols-1">
              {lastOpened && <ContinueCard score={lastOpened} />}
              <UploadDropzone />
            </div>

            <div className="mt-9">
              <div className="mb-4 flex items-center justify-between gap-6 max-md:flex-wrap">
                <div className="whitespace-nowrap text-[13px] tracking-[0.08em] text-faint">
                  ON YOUR STAND
                </div>
                <div className="flex items-center gap-3">
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search scores…"
                    className="nota-input w-55 rounded-pill border border-line bg-card px-4 py-2 font-sans text-[13px] text-ink"
                  />
                  <button
                    onClick={cycleSort}
                    className="min-h-10 cursor-pointer whitespace-nowrap rounded-pill border border-line bg-transparent px-4 py-2 font-sans text-[13px] text-muted hover:border-pine hover:text-pine"
                    title="Change sort order"
                  >
                    Sort · {tab === 'recent' ? 'Last opened' : sortMode}
                  </button>
                </div>
              </div>

              {shelf.length > 0 ? (
                <div className="grid grid-cols-3 gap-4.5 max-lg:grid-cols-2 max-md:grid-cols-1">
                  {shelf.map((score, i) => (
                    <ScoreCard key={score.id} score={score} delay={i * 60} />
                  ))}
                </div>
              ) : (
                <div className="py-12 text-center text-sm text-faint">
                  {emptyLine(tab, search.trim())}
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
