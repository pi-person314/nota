import { create } from 'zustand'

export type ScoreFormat = 'xml' | 'mxl'

export interface Score {
  id: string
  title: string
  composer?: string
  part?: string
  starred: boolean
  marks: number
  data?: string | ArrayBuffer
  format?: ScoreFormat
  fileName?: string
  thumbnail?: string
  pending?: boolean
  openedAt: number
  modifiedAt: number
  lastPage: number
  totalPages?: number
  lastSaid?: string
}

export const SORT_MODES = ['Last opened', 'Last modified', 'Name A–Z'] as const
export type SortMode = (typeof SORT_MODES)[number]
export type ShelfTab = 'library' | 'recent' | 'starred'

const HOUR = 3_600_000
const DAY = 24 * HOUR
const now = Date.now()

const SEED_SCORES: Score[] = [
  {
    id: 'nocturne', title: 'Nocturne Op. 9 No. 2', composer: 'Chopin', part: 'Piano',
    starred: true, marks: 56, openedAt: now - 2 * HOUR, modifiedAt: now - 2 * HOUR,
    lastPage: 2, totalPages: 4, lastSaid: 'crescendo from bar twelve to fourteen',
  },
  {
    id: 'symphony5', title: 'Symphony No. 5', composer: 'Beethoven', part: 'Violin I',
    starred: false, marks: 48, openedAt: now - DAY, modifiedAt: now - DAY, lastPage: 1,
  },
  {
    id: 'draft', title: 'My Composition Draft', composer: 'Untitled',
    starred: false, marks: 12, openedAt: now - 5 * HOUR, modifiedAt: now - 5 * HOUR, lastPage: 1,
  },
  {
    id: 'k545', title: 'Piano Sonata K545', composer: 'Mozart',
    starred: true, marks: 67, openedAt: now - 3 * DAY, modifiedAt: now - 3 * DAY, lastPage: 1,
  },
  {
    id: 'prelude', title: 'Prelude in C Major', composer: 'Bach',
    starred: false, marks: 31, openedAt: now - 5 * DAY, modifiedAt: now - 5 * DAY, lastPage: 1,
  },
  {
    id: 'clair', title: 'Clair de Lune', composer: 'Debussy',
    starred: true, marks: 24, openedAt: now - 14 * DAY, modifiedAt: now - 14 * DAY, lastPage: 1,
  },
]

interface ScoreState {
  scores: Score[]
  search: string
  sortMode: SortMode
  tab: ShelfTab
  wakeEnabled: boolean
  userName: string
  addScore: (score: Omit<Score, 'id' | 'openedAt' | 'modifiedAt' | 'lastPage'>) => string
  updateScore: (id: string, patch: Partial<Score>) => void
  removeScore: (id: string) => void
  toggleStar: (id: string) => void
  markOpened: (id: string) => void
  setSearch: (q: string) => void
  cycleSort: () => void
  setTab: (tab: ShelfTab) => void
  toggleWake: () => void
}

export const useScoreStore = create<ScoreState>((set) => ({
  scores: SEED_SCORES,
  search: '',
  sortMode: 'Last opened',
  tab: 'library',
  wakeEnabled: true,
  userName: 'Jaden',
  addScore: (score) => {
    const id = crypto.randomUUID()
    const t = Date.now()
    set((s) => ({
      scores: [{ ...score, id, openedAt: t, modifiedAt: t, lastPage: 1 }, ...s.scores],
    }))
    return id
  },
  updateScore: (id, patch) =>
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, ...patch } : sc)),
    })),
  removeScore: (id) =>
    set((s) => ({ scores: s.scores.filter((sc) => sc.id !== id) })),
  toggleStar: (id) =>
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, starred: !sc.starred } : sc)),
    })),
  markOpened: (id) =>
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, openedAt: Date.now() } : sc)),
    })),
  setSearch: (search) => set({ search }),
  cycleSort: () =>
    set((s) => ({
      sortMode: SORT_MODES[(SORT_MODES.indexOf(s.sortMode) + 1) % SORT_MODES.length],
    })),
  setTab: (tab) => set({ tab }),
  toggleWake: () => set((s) => ({ wakeEnabled: !s.wakeEnabled })),
}))

export function scoreMeta(score: Score, relative: string): string {
  return [score.composer, score.part, relative].filter(Boolean).join(' · ')
}
