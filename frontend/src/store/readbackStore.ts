import { create } from 'zustand'

const STORAGE_KEY = 'nota-readback-muted'

function initialMuted(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'true'
}

interface ReadbackState {
  muted: boolean
  toggleMuted: () => void
}

// Whether Nota reads command replies and clarifying questions aloud. Kept in
// its own tiny store (rather than on scoreStore) since it's a device-level
// preference, not something tied to any particular score.
export const useReadbackStore = create<ReadbackState>((set) => ({
  muted: initialMuted(),
  toggleMuted: () =>
    set((s) => {
      const muted = !s.muted
      localStorage.setItem(STORAGE_KEY, String(muted))
      return { muted }
    }),
}))
