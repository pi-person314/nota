import { useEffect, useRef, useState } from 'react'
import { PorcupineWorker } from '@picovoice/porcupine-web'
import { WebVoiceProcessor } from '@picovoice/web-voice-processor'

// Porcupine needs two files that aren't checked into the repo: a trained
// keyword model for the wake phrase, and the (language-generic) engine
// parameter model it's matched against. Both are expected to be dropped
// into the public directory so they're served as static assets.
const KEYWORD_PATH = '/hey-nota.ppn'
const MODEL_PATH = '/porcupine_params.pv'
const KEYWORD_LABEL = 'Hey Nota'

interface UseWakeWordOptions {
  // Suspends active listening without tearing down the underlying engine —
  // used to stop Nota from waking itself up while it's talking or already
  // recording.
  enabled: boolean
  onWake: () => void
}

interface UseWakeWordResult {
  // True once an access key and both model files were found and the engine
  // initialized successfully. Callers should treat this as "the feature
  // exists on this device" — independent of whether it's currently armed.
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
    // that would otherwise make a missing keyword/model file look present.
    // Neither file is ever HTML, so that's enough to tell the two apart.
    const contentType = res.headers.get('content-type') ?? ''
    return !contentType.includes('text/html')
  } catch {
    return false
  }
}

// Wraps Porcupine + WebVoiceProcessor to listen for a custom "Hey Nota" wake
// phrase. Everything about this feature is optional: no access key, no
// trained keyword file, a denied microphone prompt, or an engine that fails
// to initialize should all just leave `available` false and the rest of the
// app untouched. Nothing here throws or blocks rendering.
export function useWakeWord({ enabled, onWake }: UseWakeWordOptions): UseWakeWordResult {
  const [available, setAvailable] = useState(false)
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const workerRef = useRef<PorcupineWorker | null>(null)
  const subscribedRef = useRef(false)
  const onWakeRef = useRef(onWake)
  useEffect(() => {
    onWakeRef.current = onWake
  }, [onWake])
  // Mirrors `enabled` for the detection callback below, which is registered
  // once at worker creation and can't close over a fresh value each render.
  // Guards against a detection that was already in flight over the worker's
  // message channel landing just after `enabled` flips off (e.g. the
  // musician's own wake phrase triggering readback, which then wakes the
  // mic right back up) — unsubscribing alone stops future audio but can't
  // retract a message already on its way.
  const enabledRef = useRef(enabled)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  // Probe prerequisites and spin up the Porcupine worker once. This never
  // touches the microphone by itself — WebVoiceProcessor.subscribe is what
  // triggers the permission prompt — so `available` can be known (and a
  // toggle shown) before the musician opts in to actually listening.
  useEffect(() => {
    let cancelled = false

    async function init() {
      const accessKey = import.meta.env.VITE_PICOVOICE_ACCESS_KEY as string | undefined
      if (!accessKey) {
        // Not configured — this is the default, unremarkable state for
        // anyone who hasn't set up the wake word yet, so stay quiet.
        return
      }

      const [hasKeyword, hasModel] = await Promise.all([assetExists(KEYWORD_PATH), assetExists(MODEL_PATH)])
      if (cancelled) return
      if (!hasKeyword || !hasModel) {
        console.warn('Wake word unavailable: missing keyword or model file in the public directory.')
        return
      }

      try {
        const worker = await PorcupineWorker.create(
          accessKey,
          { publicPath: KEYWORD_PATH, label: KEYWORD_LABEL },
          () => {
            if (enabledRef.current) onWakeRef.current()
          },
          { publicPath: MODEL_PATH },
        )
        if (cancelled) {
          void worker.release()
          worker.terminate()
          return
        }
        workerRef.current = worker
        setAvailable(true)
      } catch (err) {
        console.warn('Wake word unavailable: Porcupine failed to initialize.', err)
      }
    }

    void init()

    return () => {
      cancelled = true
    }
  }, [])

  // Subscribe to / unsubscribe from the microphone as `enabled` changes,
  // without recreating the (comparatively expensive) worker each time.
  useEffect(() => {
    const worker = workerRef.current
    if (!available || !enabled || !worker) return

    let cancelled = false
    WebVoiceProcessor.subscribe(worker)
      .then(() => {
        if (cancelled) {
          void WebVoiceProcessor.unsubscribe(worker)
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
        void WebVoiceProcessor.unsubscribe(worker)
      }
      setListening(false)
    }
  }, [available, enabled])

  // Release the worker entirely on unmount.
  useEffect(() => {
    return () => {
      const worker = workerRef.current
      if (!worker) return
      if (subscribedRef.current) {
        subscribedRef.current = false
        void WebVoiceProcessor.unsubscribe(worker)
      }
      void worker.release()
      worker.terminate()
    }
  }, [])

  return { available, listening, error }
}
