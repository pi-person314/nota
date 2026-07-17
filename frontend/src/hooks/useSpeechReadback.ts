import { useCallback, useEffect, useRef } from 'react'
import { useReadbackStore } from '../store/readbackStore'

// Some browsers occasionally fail to fire the `end` event for an utterance
// (a long-standing bug in Chrome, especially once a tab loses focus).
// Without a fallback, anything waiting on onEnd — like re-arming the mic —
// would stay stuck forever, so speech is force-ended after this long.
const MAX_UTTERANCE_MS = 15_000

interface UseSpeechReadbackResult {
  // False when the Web Speech API isn't available in this browser at all
  // (older Safari, some embedded webviews, etc). Callers don't need to
  // branch on this themselves — speak() just becomes a no-op.
  supported: boolean
  // Speaks `text` aloud unless readback is muted or unsupported. `onEnd`
  // fires once, either when the utterance actually finishes (or errors) or
  // immediately if nothing was spoken — so callers can treat it as "safe to
  // proceed" regardless of whether speech happened.
  speak: (text: string, onEnd?: () => void) => void
  // Stops any speech currently in flight without invoking its onEnd.
  cancel: () => void
}

// Thin wrapper around window.speechSynthesis for reading command replies and
// clarifying questions aloud. Kept in one place so the rest of the app never
// touches speechSynthesis directly, and so the mute preference (persisted in
// readbackStore) is respected consistently everywhere speech is triggered.
export function useSpeechReadback(): UseSpeechReadbackResult {
  const muted = useReadbackStore((s) => s.muted)
  // Checked by truthiness rather than `'speechSynthesis' in window`: some
  // environments (older Safari, embedded webviews, certain test harnesses)
  // declare the property but leave it null/undefined rather than omitting
  // it entirely, which `in` would still count as "available".
  const supported = typeof window !== 'undefined' && Boolean(window.speechSynthesis) && typeof SpeechSynthesisUtterance !== 'undefined'
  const timeoutRef = useRef<number | null>(null)

  const clearFallbackTimer = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const cancel = useCallback(() => {
    clearFallbackTimer()
    if (supported) window.speechSynthesis.cancel()
  }, [supported, clearFallbackTimer])

  const speak = useCallback(
    (text: string, onEnd?: () => void) => {
      const trimmed = text.trim()
      if (!supported || muted || !trimmed) {
        onEnd?.()
        return
      }

      // Cancelling first guarantees at most one utterance is ever in
      // flight, so a fast sequence of replies can't overlap or queue up.
      window.speechSynthesis.cancel()
      clearFallbackTimer()

      const utterance = new SpeechSynthesisUtterance(trimmed)
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        clearFallbackTimer()
        onEnd?.()
      }
      utterance.onend = finish
      utterance.onerror = finish
      timeoutRef.current = window.setTimeout(finish, MAX_UTTERANCE_MS)

      window.speechSynthesis.speak(utterance)
    },
    [supported, muted, clearFallbackTimer],
  )

  // Stop any speech in flight if whatever's using this hook goes away —
  // e.g. the viewer unmounts mid-utterance when the musician navigates off.
  useEffect(() => cancel, [cancel])

  return { supported, speak, cancel }
}
