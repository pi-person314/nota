import { useMemo } from 'react'
import { useScoreStore, type Score, type SortMode, type ShelfTab } from '../store/scoreStore'
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
  return 'Nothing here yet.'
}

export function Dashboard() {
  const scores = useScoreStore((s) => s.scores)
  const search = useScoreStore((s) => s.search)
  const setSearch = useScoreStore((s) => s.setSearch)
  const sortMode = useScoreStore((s) => s.sortMode)
  const cycleSort = useScoreStore((s) => s.cycleSort)
  const tab = useScoreStore((s) => s.tab)
  const userName = useScoreStore((s) => s.userName)

  const lastOpened = useMemo(
    () => (scores.length ? [...scores].sort((a, b) => b.openedAt - a.openedAt)[0] : undefined),
    [scores],
  )

  const shelf = useMemo(() => {
    let list = scores
    if (tab === 'starred') list = list.filter((s) => s.starred)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (s) =>
          s.title.toLowerCase().includes(q) || (s.composer ?? '').toLowerCase().includes(q),
      )
    }
    return sortScores(list, tab === 'recent' ? 'Last opened' : sortMode)
  }, [scores, tab, search, sortMode])

  const hasScores = scores.length > 0
  const lastIn = lastOpened ? (lastOpened.composer ?? lastOpened.title) : ''

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <Navbar />
      <main className="rise mx-auto w-full max-w-310 flex-1 px-12 pb-16 pt-11 max-md:px-6">
        <h1 className="m-0 font-display text-[40px] font-normal leading-tight text-ink">
          {timeOfDayGreeting()}, {userName}.
        </h1>
        {hasScores && (
          <p className="mt-2 text-[15px] text-muted">
            {countWord(scores.length)} {scores.length === 1 ? 'score' : 'scores'} on your stand.
            {lastIn && ` You were last in the ${lastIn}.`}
          </p>
        )}

        {!hasScores ? (
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
