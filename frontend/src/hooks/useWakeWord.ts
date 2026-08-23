import { useEffect, useRef, useState } from 'react'
import { WebVoiceProcessor } from '@picovoice/web-voice-processor'
import { WakeWordEngine } from '../lib/wakeWordEngine'

// openWakeWord needs three ONNX models that aren't checked into the repo:
// the two shared, language-generic melspectrogram and embedding models, and
// a keyword model trained on the specific wake phrase. All three are
// expected to be dropped into the public directory so they're served as
// static assets — no account or access key required.
const MELSPECTROGRAM_PATH = '/oww/melspectrogram.onnx'
const EMBEDDING_PATH = '/oww/embedding_model.onnx'
const DEFAULT_KEYWORD_PATH = '/oww/hey_nota.onnx'
const DEFAULT_THRESHOLD = 0.5

function resolveKeywordPath(): string {
  const configured = import.meta.env.VITE_WAKE_WORD_MODEL as string | undefined
  return configured && configured.trim() !== '' ? configured : DEFAULT_KEYWORD_PATH
}

function resolveThreshold(): number {
  const raw = import.meta.env.VITE_WAKE_WORD_THRESHOLD as string | undefined
  const parsed = raw ? Number.parseFloat(raw) : NaN
  if (!Number.isFinite(parsed) || parsed <= 0 || parsed >= 1) return DEFAULT_THRESHOLD
  return parsed
}

interface UseWakeWordOptions {
  // Suspends active listening without tearing down the underlying engine —
  // used to stop Nota from waking itself up while it's talking or already
  // recording.
  enabled: boolean
  onWake: () => void
}

interface UseWakeWordResult {
  // True once the three model files were found and the engine initialized
  // successfully. Callers should treat this as "the feature exists on this
  // device" — independent of whether it's currently armed.
  available: boolean
  // True while the microphone is actually subscribed and being scanned for
  // the wake phrase.
  listening: boolean
  error: string | null
}

async function assetExists(path: string): Promise<boolean> {
  try {
    const res = await fetch(path, { method: 'HEAD' })
    if (!res.ok) return false
    // Dev servers (and some static hosts) answer an unmatched path with a
    // 200 for index.html rather than a real 404 — a client-routing fallback
    // that would otherwise make a missing model file look present. None of
    // the model files are ever HTML, so that's enough to tell the two apart.
    const contentType = res.headers.get('content-type') ?? ''
    return !contentType.includes('text/html')
  } catch {
    return false
  }
}

// Wraps a from-scratch openWakeWord engine + WebVoiceProcessor to listen for
// a custom "Hey Nota" wake phrase. Everything about this feature is
// optional: missing model files, a denied microphone prompt, or an engine
// that fails to initialize should all just leave `available` false and the
// rest of the app untouched. Nothing here throws or blocks rendering.
export function useWakeWord({ enabled, onWake }: UseWakeWordOptions): UseWakeWordResult {
  const [available, setAvailable] = useState(false)
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const engineRef = useRef<WakeWordEngine | null>(null)
  const subscribedRef = useRef(false)
  const onWakeRef = useRef(onWake)
  useEffect(() => {
    onWakeRef.current = onWake
  }, [onWake])
  // Mirrors `enabled` for the detection callback below, which is registered
  // once at engine creation and can't close over a fresh value each render.
  // Guards against a detection that was already in flight over the audio
  // pipeline landing just after `enabled` flips off (e.g. the musician's own
  // wake phrase triggering readback, which then wakes the mic right back
  // up) — unsubscribing alone stops future audio but can't retract a
  // detection already on its way.
  const enabledRef = useRef(enabled)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  // Probe prerequisites and spin up the wake word engine once. This never
  // touches the microphone by itself — WebVoiceProcessor.subscribe is what
  // triggers the permission prompt — so `available` can be known (and a
  // toggle shown) before the musician opts in to actually listening.
  useEffect(() => {
    let cancelled = false

    async function init() {
      const keywordPath = resolveKeywordPath()
      const [hasMelspectrogram, hasEmbedding, hasKeyword] = await Promise.all([
        assetExists(MELSPECTROGRAM_PATH),
        assetExists(EMBEDDING_PATH),
        assetExists(keywordPath),
      ])
      if (cancelled) return
      if (!hasMelspectrogram || !hasEmbedding || !hasKeyword) {
        console.warn('Wake word unavailable: missing one or more openWakeWord model files in the public directory.')
        return
      }

      try {
        const engine = await WakeWordEngine.create(
          {
            melspectrogramModelPath: MELSPECTROGRAM_PATH,
            embeddingModelPath: EMBEDDING_PATH,
            keywordModelPath: keywordPath,
            threshold: resolveThreshold(),
          },
          () => {
            if (enabledRef.current) onWakeRef.current()
          },
        )
        if (cancelled) {
          void engine.release()
          return
        }
        engineRef.current = engine
        setAvailable(true)
      } catch (err) {
        console.warn('Wake word unavailable: openWakeWord engine failed to initialize.', err)
      }
    }

    void init()

    return () => {
      cancelled = true
    }
  }, [])

  // Subscribe to / unsubscribe from the microphone as `enabled` changes,
  // without recreating the (comparatively expensive) engine each time.
  useEffect(() => {
    const engine = engineRef.current
    if (!available || !enabled || !engine) return

    let cancelled = false
    // Stale audio from a previous listening session (or a previous
    // detection's refractory window) shouldn't be able to trigger a wake
    // the moment we start listening again.
    engine.reset()
    WebVoiceProcessor.subscribe(engine)
      .then(() => {
        if (cancelled) {
          void WebVoiceProcessor.unsubscribe(engine)
          return
        }
        subscribedRef.current = true
        setError(null)
        setListening(true)
      })
      .catch((err) => {
        if (cancelled) return
        // Most commonly a denied or blocked microphone permission. Treat
        // the whole feature as unavailable rather than retrying forever.
        console.warn('Wake word disabled: microphone access unavailable.', err)
        setAvailable(false)
        setError(err instanceof Error ? err.message : 'Microphone access unavailable.')
      })

    return () => {
      cancelled = true
      if (subscribedRef.current) {
        subscribedRef.current = false
        void WebVoiceProcessor.unsubscribe(engine)
      }
      setListening(false)
    }
  }, [available, enabled])

  // Release the engine entirely on unmount.
  useEffect(() => {
    return () => {
      const engine = engineRef.current
      if (!engine) return
      if (subscribedRef.current) {
        subscribedRef.current = false
        void WebVoiceProcessor.unsubscribe(engine)
      }
      void engine.release()
    }
  }, [])

  return { available, listening, error }
}
