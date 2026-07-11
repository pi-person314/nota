import { create } from 'zustand'
import { api, type ScoreDetail, type ScoreSummary } from '../lib/api'
import { renderThumbnail } from '../hooks/useVerovio'

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

type ActionResult = { ok: true } | { ok: false; message: string }

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

// Some backend timestamps come back without a UTC offset (e.g. from PATCH
// or GET, unlike the upload response); without one, JS parses the string
// as local time, which skews "time ago" displays. The backend always
// stores UTC, so assume UTC when no offset is present.
function parseServerDate(iso: string): number {
  const hasOffset = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso)
  const parsed = Date.parse(hasOffset ? iso : `${iso}Z`)
  return Number.isNaN(parsed) ? Date.now() : parsed
}

// Backend score summaries carry no MusicXML; local-only fields (thumbnail,
// pagination, cached document text) are preserved from whatever entry
// already existed for this id, since they aren't part of the server contract.
function mapSummary(summary: ScoreSummary, existing?: Score): Score {
  return {
    id: summary.id,
    title: summary.name,
    part: summary.part_name ?? undefined,
    starred: summary.is_starred,
    marks: summary.measure_count,
    openedAt: parseServerDate(summary.last_opened_at),
    modifiedAt: parseServerDate(summary.last_modified_at),
    lastPage: existing?.lastPage ?? 1,
    totalPages: existing?.totalPages,
    data: existing?.data,
    format: existing?.format ?? 'xml',
    thumbnail: existing?.thumbnail,
    fileName: existing?.fileName,
    lastSaid: existing?.lastSaid,
    pending: false,
  }
}

function mapDetail(detail: ScoreDetail, existing?: Score): Score {
  return {
    ...mapSummary(detail, existing),
    data: detail.musicxml,
    format: 'xml',
  }
}

interface ScoreState {
  scores: Score[]
  search: string
  sortMode: SortMode
  tab: ShelfTab
  wakeEnabled: boolean
  loading: boolean
  loadError: string | null

  fetchScores: () => Promise<void>
  uploadScore: (file: File) => Promise<{ ok: true; id: string } | { ok: false; message: string }>
  loadScoreDetail: (id: string) => Promise<ActionResult>
  updateScore: (id: string, patch: Partial<Score>) => void
  renameScore: (id: string, title: string) => Promise<void>
  toggleStar: (id: string) => Promise<void>
  removeScore: (id: string) => Promise<void>
  markOpened: (id: string) => void
  setSearch: (q: string) => void
  cycleSort: () => void
  setTab: (tab: ShelfTab) => void
  toggleWake: () => void
  reset: () => void
}

export const useScoreStore = create<ScoreState>((set, get) => ({
  scores: [],
  search: '',
  sortMode: 'Last opened',
  tab: 'library',
  wakeEnabled: true,
  loading: false,
  loadError: null,

  fetchScores: async () => {
    set({ loading: true, loadError: null })
    try {
      const summaries = await api.listScores()
      set((s) => {
        const byId = new Map(s.scores.map((sc) => [sc.id, sc]))
        return {
          scores: summaries.map((sum) => mapSummary(sum, byId.get(sum.id))),
          loading: false,
        }
      })
    } catch (err) {
      set({ loading: false, loadError: errorMessage(err, 'Could not load your scores.') })
    }
  },

  uploadScore: async (file) => {
    try {
      const summary = await api.uploadScore(file)
      const score = mapSummary(summary)
      set((s) => ({ scores: [{ ...score, pending: true }, ...s.scores] }))

      try {
        const detail = await api.getScore(summary.id)
        const rendered = await renderThumbnail(detail.musicxml, 'xml')
        set((s) => ({
          scores: s.scores.map((sc) =>
            sc.id === summary.id
              ? {
                  ...sc,
                  data: detail.musicxml,
                  format: 'xml',
                  thumbnail: rendered?.svg,
                  totalPages: rendered?.pageCount,
                  pending: false,
                }
              : sc,
          ),
        }))
      } catch {
        // The score is already saved server-side; a failed thumbnail
        // render is cosmetic only, so just clear the pending flag.
        set((s) => ({
          scores: s.scores.map((sc) => (sc.id === summary.id ? { ...sc, pending: false } : sc)),
        }))
      }

      return { ok: true, id: summary.id }
    } catch (err) {
      return { ok: false, message: errorMessage(err, 'Upload failed.') }
    }
  },

  loadScoreDetail: async (id) => {
    try {
      const detail = await api.getScore(id)
      set((s) => {
        const idx = s.scores.findIndex((sc) => sc.id === id)
        const merged = mapDetail(detail, idx >= 0 ? s.scores[idx] : undefined)
        const scores =
          idx >= 0 ? s.scores.map((sc, i) => (i === idx ? merged : sc)) : [merged, ...s.scores]
        return { scores }
      })
      return { ok: true }
    } catch (err) {
      return { ok: false, message: errorMessage(err, 'Could not load this score.') }
    }
  },

  updateScore: (id, patch) =>
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, ...patch } : sc)),
    })),

  renameScore: async (id, title) => {
    const trimmed = title.trim()
    const prev = get().scores.find((sc) => sc.id === id)
    if (!prev || !trimmed || trimmed === prev.title) return
    set((s) => ({
      scores: s.scores.map((sc) =>
        sc.id === id ? { ...sc, title: trimmed, modifiedAt: Date.now() } : sc,
      ),
    }))
    try {
      await api.updateScore(id, { name: trimmed })
    } catch {
      set((s) => ({
        scores: s.scores.map((sc) =>
          sc.id === id ? { ...sc, title: prev.title, modifiedAt: prev.modifiedAt } : sc,
        ),
      }))
    }
  },

  toggleStar: async (id) => {
    const prev = get().scores.find((sc) => sc.id === id)
    if (!prev) return
    const nextStarred = !prev.starred
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, starred: nextStarred } : sc)),
    }))
    try {
      await api.updateScore(id, { is_starred: nextStarred })
    } catch {
      set((s) => ({
        scores: s.scores.map((sc) => (sc.id === id ? { ...sc, starred: prev.starred } : sc)),
      }))
    }
  },

  removeScore: async (id) => {
    const prevScores = get().scores
    set((s) => ({ scores: s.scores.filter((sc) => sc.id !== id) }))
    try {
      await api.deleteScore(id)
    } catch {
      set({ scores: prevScores })
    }
  },

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
  reset: () => set({ scores: [], search: '', tab: 'library', loadError: null }),
}))

export function scoreMeta(score: Score, relative: string): string {
  return [score.composer, score.part, relative].filter(Boolean).join(' · ')
}
