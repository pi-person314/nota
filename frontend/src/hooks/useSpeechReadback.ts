import { useCallback, useEffect, useRef, useState } from 'react'
import { useReadbackStore } from '../store/readbackStore'

// Chrome has a long-standing bug where a single long SpeechSynthesisUtterance
// tends to stall or silently drop its `end` event somewhere around 15
// seconds in, especially once the tab loses focus. The standard workaround
// (and the one used here) is to never hand the browser one long utterance in
// the first place: split the reply into sentence-sized chunks and speak them
// back to back, chaining off each chunk's own `end` event. That keeps every
// individual utterance well clear of the stall point, so the fallback timer
// below almost never has to intervene for legitimate speech.

// Upper bound on how long a single chunk is allowed to run before we give up
// on it and force it to finish. This is per CHUNK, not per reply — a long
// reply is many chunks, each getting its own budget. Scaled a little by
// chunk length (a few words shouldn't wait as long as ~200 chars would) but
// capped well under where Chrome's stall tends to bite.
const MIN_CHUNK_TIMEOUT_MS = 4_000
const MAX_CHUNK_TIMEOUT_MS = 12_000
const MS_PER_CHAR = 110

// Chunks are kept comfortably short so no single utterance gets anywhere
// near Chrome's stall point.
const MAX_CHUNK_LENGTH = 200

function chunkTimeoutMs(chunk: string): number {
  return Math.min(MAX_CHUNK_TIMEOUT_MS, Math.max(MIN_CHUNK_TIMEOUT_MS, chunk.length * MS_PER_CHAR))
}

// Splits text into sentence-ish, speech-friendly chunks. Sentences are kept
// together where possible (splitting mid-sentence produces an awkward pause
// on real TTS voices), tiny fragments left over from the split (e.g. "Dr."
// followed by a short remainder, or a lone trailing word) are merged back
// into a neighbor so they don't become their own oddly-clipped utterance,
// and anything still too long to speak safely in one utterance is
// hard-split at word boundaries as a last resort.
function chunkText(text: string): string[] {
  // Split on sentence terminators and newlines, keeping the terminator
  // attached to the sentence it ends.
  const rough = text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean)

  if (rough.length === 0) return []

  // Merge short fragments into the previous chunk so we don't end up
  // speaking single words or short clauses as their own utterance.
  const MIN_MERGE_LENGTH = 20
  const merged: string[] = []
  for (const piece of rough) {
    const prev = merged[merged.length - 1]
    if (prev && (prev.length < MIN_MERGE_LENGTH || piece.length < MIN_MERGE_LENGTH) && (prev.length + 1 + piece.length) <= MAX_CHUNK_LENGTH) {
      merged[merged.length - 1] = `${prev} ${piece}`
    } else {
      merged.push(piece)
    }
  }

  // Hard-split anything still too long, breaking on word boundaries so we
  // never cut a word in half.
  const chunks: string[] = []
  for (const piece of merged) {
    if (piece.length <= MAX_CHUNK_LENGTH) {
      chunks.push(piece)
      continue
    }
    const words = piece.split(/\s+/)
    let current = ''
    for (const word of words) {
      const candidate = current ? `${current} ${word}` : word
      if (candidate.length > MAX_CHUNK_LENGTH && current) {
        chunks.push(current)
        current = word
      } else {
        current = candidate
      }
    }
    if (current) chunks.push(current)
  }

  return chunks
}

interface UseSpeechReadbackResult {
  // False when the Web Speech API isn't available in this browser at all
  // (older Safari, some embedded webviews, etc). Callers don't need to
  // branch on this themselves — speak() just becomes a no-op.
  supported: boolean
  // True from the moment the first chunk of an utterance starts until the
  // last chunk finishes (or the sequence is cancelled/timed out) — false the
  // rest of the time, including while muted or unsupported, and it does not
  // flicker between chunks. Useful for callers that need to suspend
  // something (like wake word detection) for as long as Nota is talking.
  speaking: boolean
  // Speaks `text` aloud unless readback is muted or unsupported, splitting
  // it into sentence-sized chunks spoken back to back. `onEnd` fires once,
  // either when the whole sequence actually finishes (or errors/times out)
  // or immediately if nothing was spoken — so callers can treat it as "safe
  // to proceed" regardless of whether speech happened.
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
  const [speaking, setSpeaking] = useState(false)

  // Identifies one call to speak() through its whole chunk sequence. Bumped
  // on every new speak()/cancel(), and captured by each chunk's callbacks so
  // a stale event from an old, already-dead sequence (e.g. an `onend` or
  // `onerror` that speechSynthesis.cancel() triggers on the utterance it
  // just interrupted) can't advance or settle a sequence that isn't current
  // anymore.
  const generationRef = useRef(0)
  // The onEnd for the currently in-flight speak() call, and whether it's
  // already been invoked — mirrors the old per-utterance `settled` flag but
  // now covers a whole chunk sequence instead of a single utterance, since
  // onEnd must fire exactly once per speak() regardless of how many chunks
  // it took.
  const settledRef = useRef(true)
  const onEndRef = useRef<(() => void) | undefined>(undefined)

  const clearFallbackTimer = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  // Ends the current sequence and calls its onEnd, but only once and only
  // if it's still the live sequence — guards against duplicate settle calls
  // (e.g. a timeout firing right as the browser's own onend arrives).
  const settle = useCallback(
    (generation: number) => {
      if (generation !== generationRef.current || settledRef.current) return
      settledRef.current = true
      clearFallbackTimer()
      setSpeaking(false)
      onEndRef.current?.()
    },
    [clearFallbackTimer],
  )

  const cancel = useCallback(() => {
    // Bump the generation first so any events the upcoming
    // speechSynthesis.cancel() triggers on the in-flight utterance are
    // recognized as stale and ignored.
    generationRef.current += 1
    settledRef.current = true
    onEndRef.current = undefined
    clearFallbackTimer()
    if (supported) window.speechSynthesis.cancel()
    setSpeaking(false)
  }, [supported, clearFallbackTimer])

  const speak = useCallback(
    (text: string, onEnd?: () => void) => {
      const trimmed = text.trim()
      const chunks = trimmed ? chunkText(trimmed) : []

      // Cancelling first guarantees at most one sequence is ever in flight,
      // so a fast run of replies can't overlap or interleave their chunks.
      // This also settles (without calling onEnd) whatever sequence was
      // previously in progress.
      generationRef.current += 1
      clearFallbackTimer()
      if (supported) window.speechSynthesis.cancel()

      if (!supported || muted || chunks.length === 0) {
        settledRef.current = true
        onEndRef.current = undefined
        setSpeaking(false)
        onEnd?.()
        return
      }

      const generation = generationRef.current
      settledRef.current = false
      onEndRef.current = onEnd
      setSpeaking(true)

      const speakChunk = (index: number) => {
        // A newer speak()/cancel() has taken over since this was scheduled.
        if (generation !== generationRef.current) return

        if (index >= chunks.length) {
          settle(generation)
          return
        }

        const utterance = new SpeechSynthesisUtterance(chunks[index])
        let chunkSettled = false

        const advance = () => {
          if (chunkSettled || generation !== generationRef.current) return
          chunkSettled = true
          clearFallbackTimer()
          speakChunk(index + 1)
        }
        // A genuinely stuck or errored chunk aborts the rest of the
        // sequence rather than trying to press on to the next one — same
        // as the old single-utterance behavior, just scoped to whichever
        // chunk got stuck. Both paths cancel speechSynthesis first so
        // nothing keeps playing after we've told callers speech is done.
        const abort = () => {
          if (chunkSettled || generation !== generationRef.current) return
          chunkSettled = true
          window.speechSynthesis.cancel()
          settle(generation)
        }

        utterance.onend = advance
        utterance.onerror = abort
        timeoutRef.current = window.setTimeout(abort, chunkTimeoutMs(chunks[index]))
        window.speechSynthesis.speak(utterance)
      }

      speakChunk(0)
    },
    [supported, muted, clearFallbackTimer, settle],
  )

  // Muting mid-reply stops the current one immediately rather than letting
  // it play out — muting is a "stop talking" gesture, not just a preference
  // for next time. Unlike cancel(), the sequence's onEnd still fires: a
  // caller waiting on speech to finish before acting (the mic re-arming
  // itself after a clarifying question) should proceed as if the reply had
  // ended normally, not wait forever on speech that will never come.
  // Driven by a store subscription rather than the rendered `muted` value so
  // this reacts to the moment muting happens, and only then.
  useEffect(
    () =>
      useReadbackStore.subscribe((state, prevState) => {
        if (!state.muted || prevState.muted || settledRef.current) return
        const onEnd = onEndRef.current
        // Bumped before cancelling so the `end`/`error` events that
        // speechSynthesis.cancel() fires on the interrupted utterance are
        // seen as stale and can't advance the sequence to its next chunk.
        generationRef.current += 1
        settledRef.current = true
        onEndRef.current = undefined
        clearFallbackTimer()
        if (supported) window.speechSynthesis.cancel()
        setSpeaking(false)
        onEnd?.()
      }),
    [supported, clearFallbackTimer],
  )

  // Stop any speech in flight if whatever's using this hook goes away —
  // e.g. the viewer unmounts mid-utterance when the musician navigates off.
  useEffect(() => cancel, [cancel])

  return { supported, speaking, speak, cancel }
}
