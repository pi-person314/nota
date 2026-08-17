// Thin typed wrapper around the Flask backend's JSON API. All requests are
// same-origin (proxied by Vite in dev) and include the session cookie, so
// no token handling is needed on this side — the server tracks the logged
// in user via a signed cookie.

const BASE = '/api'

export class ApiRequestError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData
  const headers: Record<string, string> = isFormData
    ? {}
    : init?.body
      ? { 'Content-Type': 'application/json' }
      : {}

  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  })

  const text = await res.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!res.ok) {
    const body = (payload ?? {}) as { error?: string; message?: string }
    throw new ApiRequestError(
      res.status,
      body.error ?? 'UNKNOWN_ERROR',
      body.message ?? res.statusText ?? 'Something went wrong.',
    )
  }

  return payload as T
}

export interface User {
  id: string
  name: string
  email: string
}

export interface ScoreSummary {
  id: string
  name: string
  part_name: string | null
  is_starred: boolean
  is_archived: boolean
  from_pdf: boolean
  measure_count: number
  has_pickup?: boolean
  created_at: string
  last_opened_at: string
  last_modified_at: string
  has_thumbnail?: boolean
}

export interface ScorePart {
  id: string
  name: string
}

export interface TimeSignatureEntry {
  measure: number
  ts: string
}

export interface ScoreDetail extends ScoreSummary {
  parts?: ScorePart[]
  time_signatures?: TimeSignatureEntry[]
  musicxml: string
}

// Only present on the upload endpoint's response, and only for PDF
// (OMR) imports: user-facing sentences flagging lower-confidence
// recognition that didn't fail outright. Absent for native
// MusicXML/.mxl uploads, and an empty array for a clean PDF import.
export interface UploadResponse extends ScoreSummary {
  omr_warnings?: string[]
}

export type SortKey = 'last_opened' | 'last_modified' | 'date_uploaded' | 'name_asc' | 'name_desc'

export interface CommandResult {
  musicxml: string
  changed_element_ids: string[]
  confirmation: string
  tools_called: string[]
  needs_clarification: boolean
}

export interface UndoRedoResult {
  musicxml: string
  summary: string
  changed_element_ids: string[]
}

export interface HistoryItem {
  id: number
  transcript: string
  confirmation: string
  tools_called: string[]
  created_at: string
}

export interface HistoryResponse {
  items: HistoryItem[]
}

export interface TranscribeResult {
  text: string
}

export interface ThumbnailPayload {
  svg: string
  page_count: number | null
}

export const api = {
  signup(name: string, email: string, password: string) {
    return request<User>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    })
  },
  login(email: string, password: string) {
    return request<User>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },
  logout() {
    return request<{ ok: boolean }>('/auth/logout', { method: 'POST' })
  },
  me() {
    return request<User>('/auth/me')
  },

  listScores(params?: { sort?: SortKey; starred?: boolean; archived?: 'true' | 'false' | 'all' }) {
    const qs = new URLSearchParams()
    if (params?.sort) qs.set('sort', params.sort)
    if (params?.starred) qs.set('starred', 'true')
    if (params?.archived) qs.set('archived', params.archived)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<ScoreSummary[]>(`/scores${suffix}`)
  },
  uploadScore(file: File) {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('/scores/upload', { method: 'POST', body: form })
  },
  getScore(id: string) {
    return request<ScoreDetail>(`/scores/${id}`)
  },
  updateScore(id: string, patch: { name?: string; is_starred?: boolean; is_archived?: boolean }) {
    return request<ScoreSummary>(`/scores/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },
  deleteScore(id: string) {
    return request<{ ok: boolean }>(`/scores/${id}`, { method: 'DELETE' })
  },
  exportUrl(id: string) {
    return `${BASE}/scores/${id}/export`
  },
  getThumbnail(id: string) {
    return request<ThumbnailPayload>(`/scores/${id}/thumbnail`)
  },
  putThumbnail(id: string, svg: string, pageCount?: number) {
    return request<{ ok: boolean }>(`/scores/${id}/thumbnail`, {
      method: 'PUT',
      body: JSON.stringify(pageCount === undefined ? { svg } : { svg, page_count: pageCount }),
    })
  },

  sendCommand(id: string, text: string) {
    return request<CommandResult>(`/scores/${id}/command`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    })
  },
  undo(id: string) {
    return request<UndoRedoResult>(`/scores/${id}/undo`, { method: 'POST' })
  },
  redo(id: string) {
    return request<UndoRedoResult>(`/scores/${id}/redo`, { method: 'POST' })
  },
  getHistory(id: string) {
    return request<HistoryResponse>(`/scores/${id}/history`)
  },

  // `blob` is the recorded audio (webm). Sent as multipart form data so the
  // browser sets the correct boundary in Content-Type — request() already
  // skips the JSON header for FormData bodies.
  transcribeAudio(blob: Blob) {
    const form = new FormData()
    form.append('audio', blob, 'recording.webm')
    return request<TranscribeResult>('/transcribe', { method: 'POST', body: form })
  },
}
