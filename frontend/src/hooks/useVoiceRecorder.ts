import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderStatus = 'idle' | 'requesting-permission' | 'recording' | 'processing'

const MAX_DURATION_MS = 30_000

interface UseVoiceRecorderOptions {
  // Called once a recording finishes and is ready to send off — not called
  // when the recording was cancelled instead of stopped.
  onRecordingReady: (blob: Blob) => void | Promise<void>
  maxDurationMs?: number
}

interface UseVoiceRecorderResult {
  status: RecorderStatus
  error: string | null
  start: () => Promise<void>
  stop: () => void
  cancel: () => void
  finish: () => void
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) return undefined
  if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) return 'audio/webm;codecs=opus'
  if (MediaRecorder.isTypeSupported('audio/webm')) return 'audio/webm'
  return undefined
}

// Wraps getUserMedia + MediaRecorder into a small state machine:
// idle -> requesting-permission -> recording -> processing -> idle.
// The caller supplies onRecordingReady, which receives the captured audio
// once recording stops (not on cancel), and is responsible for calling
// finish() when it's done acting on that audio so the mic can be used again.
export function useVoiceRecorder({
  onRecordingReady,
  maxDurationMs = MAX_DURATION_MS,
}: UseVoiceRecorderOptions): UseVoiceRecorderResult {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const maxTimerRef = useRef<number | null>(null)
  const discardRef = useRef(false)
  const onRecordingReadyRef = useRef(onRecordingReady)

  useEffect(() => {
    onRecordingReadyRef.current = onRecordingReady
  }, [onRecordingReady])

  const clearMaxTimer = () => {
    if (maxTimerRef.current !== null) {
      window.clearTimeout(maxTimerRef.current)
      maxTimerRef.current = null
    }
  }

  const releaseStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  const stop = useCallback(() => {
    clearMaxTimer()
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }
  }, [])

  const cancel = useCallback(() => {
    discardRef.current = true
    stop()
  }, [stop])

  const start = useCallback(async () => {
    if (status === 'recording' || status === 'requesting-permission') return
    setError(null)

    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Voice recording is not supported in this browser.')
      return
    }

    setStatus('requesting-permission')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const mimeType = pickMimeType()
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      chunksRef.current = []
      discardRef.current = false

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        clearMaxTimer()
        releaseStream()
        const wasDiscarded = discardRef.current
        const blob = new Blob(chunksRef.current, { type: mimeType ?? 'audio/webm' })
        chunksRef.current = []
        if (wasDiscarded) {
          setStatus('idle')
          return
        }
        setStatus('processing')
        void onRecordingReadyRef.current(blob)
      }

      mediaRecorderRef.current = recorder
      recorder.start()
      setStatus('recording')
      maxTimerRef.current = window.setTimeout(() => stop(), maxDurationMs)
    } catch (err) {
      releaseStream()
      setStatus('idle')
      const denied =
        err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')
      setError(denied ? 'Microphone access was denied.' : 'Could not access the microphone.')
    }
  }, [status, maxDurationMs, stop])

  const finish = useCallback(() => {
    setStatus((current) => (current === 'processing' ? 'idle' : current))
  }, [])

  // Release the mic and any pending timer on unmount.
  useEffect(
    () => () => {
      clearMaxTimer()
      releaseStream()
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== 'inactive') recorder.stop()
    },
    [],
  )

  return { status, error, start, stop, cancel, finish }
}
