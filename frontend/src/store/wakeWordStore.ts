import { create } from 'zustand'

const STORAGE_KEY = 'nota-wake-word-armed'

function initialArmed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'true'
}

interface WakeWordState {
  armed: boolean
  toggleArmed: () => void
}

// Whether the musician has armed the "Hey Nota" wake word listener. Kept in
// its own tiny store (like readbackStore) since it's a device-level
// preference. Starts disarmed by default — the feature only ever runs when
// it's both armed here and actually available on this device, so this
// preference is safe to persist even before the wake word is set up.
export const useWakeWordStore = create<WakeWordState>((set) => ({
  armed: initialArmed(),
  toggleArmed: () =>
    set((s) => {
      const armed = !s.armed
      localStorage.setItem(STORAGE_KEY, String(armed))
      return { armed }
    }),
}))
