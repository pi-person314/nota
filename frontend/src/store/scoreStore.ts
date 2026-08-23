import { create } from 'zustand'
import {
  api,
  ApiRequestError,
  isQueuedConversion,
  type ConversionJob,
  type ScoreDetail,
  type ScoreSummary,
} from '../lib/api'
import { renderThumbnail } from '../hooks/useVerovio'

export type ScoreFormat = 'xml' | 'mxl'

export interface Score {
  id: string
  title: string
  composer?: string
  part?: string
  starred: boolean
  archived: boolean
  fromPdf: boolean
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
export type ShelfTab = 'library' | 'recent' | 'starred' | 'archived'

type ActionResult = { ok: true } | { ok: false; message: string }
type UploadResult =
  | { ok: true; id: string; warnings?: string[] }
  | { ok: true; jobId: string }
  | { ok: false; message: string; code?: string }

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
    archived: summary.is_archived ?? false,
    fromPdf: summary.from_pdf ?? false,
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
  // Background PDF (OMR) conversion jobs this session knows about — both
  // ones it just queued and ones re-attached by resumeConversions() after
  // a page load. A job is removed once the UI that surfaced it is done
  // with it (see clearConversion); succeeded/failed jobs otherwise stick
  // around so a component that only just mounted can still read the
  // outcome of a conversion it didn't itself start.
  conversions: ConversionJob[]

  fetchScores: () => Promise<void>
  uploadScore: (file: File) => Promise<UploadResult>
  // Re-attaches polling to any of the caller's conversion jobs that are
  // still queued/running server-side. Safe to call anytime (e.g. on every
  // dashboard mount) — already-tracked or already-finished jobs are left
  // alone.
  resumeConversions: () => Promise<void>
  // Drops a finished (or abandoned) conversion job from the store and
  // stops any polling for it. Call once the UI has shown its outcome.
  clearConversion: (jobId: string) => void
  loadScoreDetail: (id: string) => Promise<ActionResult>
  updateScore: (id: string, patch: Partial<Score>) => void
  refreshThumbnail: (id: string, xml: string) => void
  renameScore: (id: string, title: string) => Promise<void>
  toggleStar: (id: string) => Promise<void>
  toggleArchive: (id: string) => Promise<void>
  removeScore: (id: string) => Promise<void>
  markOpened: (id: string) => void
  setSearch: (q: string) => void
  cycleSort: () => void
  setTab: (tab: ShelfTab) => void
  toggleWake: () => void
  reset: () => void
}

type SetScoreState = (partial: Partial<ScoreState> | ((state: ScoreState) => Partial<ScoreState>)) => void

// --- Background conversion polling -----------------------------------
//
// Timer handles and per-job bookkeeping live outside the store's state
// (rather than as store fields) since they're not serializable UI state —
// nothing renders off them directly, and keeping them here means a store
// `set()` never has to carry interval ids around.

const POLL_INTERVAL_MS = 2_000
// Stop polling a job that's been queued/running this long without
// resolving — something is very wrong server-side, and a phone left open
// on this screen shouldn't poll forever.
const POLL_CEILING_MS = 10 * 60 * 1000
// A handful of consecutive network failures (as opposed to the request
// succeeding with a failed job status) is treated as "we've lost the
// connection" rather than "the job failed" — polling just stops, leaving
// the job in its last known state; resumeConversions() will pick it back
// up on the next successful page load.
const MAX_CONSECUTIVE_POLL_FAILURES = 3

const pollTimers = new Map<string, ReturnType<typeof setInterval>>()
const pollStartedAt = new Map<string, number>()
const pollFailures = new Map<string, number>()
const pollInFlight = new Set<string>()

function stopPolling(jobId: string): void {
  const timer = pollTimers.get(jobId)
  if (timer !== undefined) clearInterval(timer)
  pollTimers.delete(jobId)
  pollStartedAt.delete(jobId)
  pollFailures.delete(jobId)
  pollInFlight.delete(jobId)
}

function stopAllPolling(): void {
  for (const jobId of Array.from(pollTimers.keys())) stopPolling(jobId)
}

function upsertConversion(set: SetScoreState, job: ConversionJob): void {
  set((s) => ({
    conversions: s.conversions.some((c) => c.id === job.id)
      ? s.conversions.map((c) => (c.id === job.id ? job : c))
      : [...s.conversions, job],
  }))
}

// The exact "fetch the finished score and render its thumbnail" logic a
// successful synchronous upload has always run, extracted so the polling
// path (which only learns the score id once its job succeeds) can reuse
// it verbatim instead of duplicating it. `prefetched` lets a caller that
// already fetched the ScoreDetail (to build a placeholder row) hand it
// over instead of triggering a second identical request.
async function finishScoreInsert(
  scoreId: string,
  set: SetScoreState,
  prefetched?: ScoreDetail,
): Promise<void> {
  try {
    const detail = prefetched ?? (await api.getScore(scoreId))
    const rendered = await renderThumbnail(detail.musicxml, 'xml')
    set((s) => ({
      scores: s.scores.map((sc) =>
        sc.id === scoreId
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
    if (rendered) {
      // Persistence is cosmetic — local state already reflects the
      // render, so a failure here is silently ignored.
      api.putThumbnail(scoreId, rendered.svg, rendered.pageCount).catch(() => {})
    }
  } catch {
    // The score is already saved server-side; a failed thumbnail render
    // is cosmetic only, so just clear the pending flag.
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === scoreId ? { ...sc, pending: false } : sc)),
    }))
  }
}

// Runs once a conversion job's poll reports `succeeded`: loads the new
// score (there's no existing row for it yet, unlike the synchronous
// upload path, since all we had until now was a job id) and inserts it
// the same way a synchronous upload does — a pending placeholder first,
// then thumbnail/data filled in.
async function finalizeConversionSuccess(scoreId: string, set: SetScoreState): Promise<void> {
  try {
    const detail = await api.getScore(scoreId)
    set((s) => {
      const existing = s.scores.find((sc) => sc.id === scoreId)
      const placeholder = { ...mapDetail(detail, existing), pending: true }
      return {
        scores: existing
          ? s.scores.map((sc) => (sc.id === scoreId ? placeholder : sc))
          : [placeholder, ...s.scores],
      }
    })
    await finishScoreInsert(scoreId, set, detail)
  } catch {
    // The job itself already reports success and is persisted
    // server-side; if we can't fetch it right now the conversion entry
    // just stays around with no error attached rather than showing a
    // false failure, and the next fetchScores() pass will pick it up.
  }
}

async function pollConversion(jobId: string, set: SetScoreState): Promise<void> {
  // Never let two ticks for the same job overlap — a slow response could
  // otherwise still be in flight when the next interval fires.
  if (pollInFlight.has(jobId)) return

  const startedAt = pollStartedAt.get(jobId)
  if (startedAt !== undefined && Date.now() - startedAt > POLL_CEILING_MS) {
    stopPolling(jobId)
    set((s) => ({
      conversions: s.conversions.map((c) =>
        c.id === jobId && (c.status === 'queued' || c.status === 'running')
          ? {
              ...c,
              status: 'failed',
              error_code: null,
              error_message: 'This is taking longer than expected — please try again.',
            }
          : c,
      ),
    }))
    return
  }

  pollInFlight.add(jobId)
  try {
    const job = await api.getConversionJob(jobId)
    pollFailures.set(jobId, 0)
    upsertConversion(set, job)
    if (job.status === 'succeeded' || job.status === 'failed') {
      stopPolling(jobId)
      if (job.status === 'succeeded' && job.score_id) {
        await finalizeConversionSuccess(job.score_id, set)
      }
    }
  } catch {
    const failures = (pollFailures.get(jobId) ?? 0) + 1
    pollFailures.set(jobId, failures)
    if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) stopPolling(jobId)
  } finally {
    pollInFlight.delete(jobId)
  }
}

// Starts (or, for a job already being polled, simply records) tracking
// for one conversion job. Safe to call repeatedly for the same job —
// polling is only ever set up once per job id.
function startPolling(job: ConversionJob, set: SetScoreState): void {
  upsertConversion(set, job)
  if (job.status !== 'queued' && job.status !== 'running') return
  if (pollTimers.has(job.id)) return
  pollStartedAt.set(job.id, Date.now())
  pollFailures.set(job.id, 0)
  pollTimers.set(
    job.id,
    setInterval(() => {
      void pollConversion(job.id, set)
    }, POLL_INTERVAL_MS),
  )
}

export const useScoreStore = create<ScoreState>((set, get) => ({
  scores: [],
  search: '',
  sortMode: 'Last opened',
  tab: 'library',
  wakeEnabled: true,
  loading: false,
  loadError: null,
  conversions: [],

  fetchScores: async () => {
    set({ loading: true, loadError: null })
    // Fire-and-forget: re-attach polling to any conversions still in
    // flight from a previous load (e.g. this is a page refresh mid PDF
    // import). Independent of the score list fetch below, so it never
    // delays fetchScores' own resolution.
    void get().resumeConversions()
    try {
      const summaries = await api.listScores({ archived: 'all' })
      set((s) => {
        const byId = new Map(s.scores.map((sc) => [sc.id, sc]))
        return {
          scores: summaries.map((sum) => mapSummary(sum, byId.get(sum.id))),
          loading: false,
        }
      })

      // Backfill thumbnails persisted server-side but not yet in memory
      // (e.g. after a page refresh). Runs in the background so it never
      // delays fetchScores' own resolution.
      const byId = new Map(get().scores.map((sc) => [sc.id, sc]))
      for (const sum of summaries) {
        if (!sum.has_thumbnail) continue
        const existing = byId.get(sum.id)
        if (!existing || existing.thumbnail) continue
        api
          .getThumbnail(sum.id)
          .then((thumb) => {
            set((s) => ({
              scores: s.scores.map((sc) =>
                sc.id === sum.id
                  ? { ...sc, thumbnail: thumb.svg, totalPages: thumb.page_count ?? sc.totalPages }
                  : sc,
              ),
            }))
          })
          .catch(() => {})
      }
    } catch (err) {
      set({ loading: false, loadError: errorMessage(err, 'Could not load your scores.') })
    }
  },

  uploadScore: async (file) => {
    try {
      const response = await api.uploadScore(file)

      // A PDF doesn't convert inline — the server queues a background OMR
      // job and hands back its id. Register it and start polling; the
      // caller finds out how it went by watching `conversions` (or the
      // `scores` list, once it succeeds) rather than from this call.
      if (isQueuedConversion(response)) {
        startPolling(
          {
            id: response.job_id,
            status: 'queued',
            filename: response.filename,
            score_id: null,
            error_code: null,
            error_message: null,
            warnings: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          set,
        )
        return { ok: true, jobId: response.job_id }
      }

      const summary = response
      const score = mapSummary(summary)
      set((s) => ({ scores: [{ ...score, pending: true }, ...s.scores] }))
      await finishScoreInsert(summary.id, set)

      return summary.omr_warnings?.length
        ? { ok: true, id: summary.id, warnings: summary.omr_warnings }
        : { ok: true, id: summary.id }
    } catch (err) {
      const code = err instanceof ApiRequestError ? err.code : undefined
      return { ok: false, message: errorMessage(err, 'Upload failed.'), code }
    }
  },

  resumeConversions: async () => {
    try {
      const { items } = await api.listConversionJobs()
      for (const job of items) {
        if (job.status === 'queued' || job.status === 'running') {
          startPolling(job, set)
        }
      }
    } catch {
      // Best-effort — any conversion truly still in progress just stays
      // invisible until the next successful call (e.g. the next mount).
    }
  },

  clearConversion: (jobId) => {
    stopPolling(jobId)
    set((s) => ({ conversions: s.conversions.filter((c) => c.id !== jobId) }))
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

  // Re-renders a score's thumbnail after its MusicXML changes (command,
  // undo, redo) and keeps the server copy in sync. Never throws and never
  // awaited by callers — a failed render/persist just leaves the previous
  // thumbnail in place.
  refreshThumbnail: (id, xml) => {
    renderThumbnail(xml, 'xml')
      .then((rendered) => {
        if (!rendered) return
        get().updateScore(id, { thumbnail: rendered.svg, totalPages: rendered.pageCount })
        api.putThumbnail(id, rendered.svg, rendered.pageCount).catch(() => {})
      })
      .catch(() => {})
  },

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

  toggleArchive: async (id) => {
    const prev = get().scores.find((sc) => sc.id === id)
    if (!prev) return
    const nextArchived = !prev.archived
    set((s) => ({
      scores: s.scores.map((sc) => (sc.id === id ? { ...sc, archived: nextArchived } : sc)),
    }))
    try {
      await api.updateScore(id, { is_archived: nextArchived })
    } catch {
      set((s) => ({
        scores: s.scores.map((sc) => (sc.id === id ? { ...sc, archived: prev.archived } : sc)),
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
  reset: () => {
    stopAllPolling()
    set({ scores: [], search: '', tab: 'library', loadError: null, conversions: [] })
  },
}))

export function scoreMeta(score: Score, relative: string): string {
  return [score.composer, score.part, relative].filter(Boolean).join(' · ')
}
