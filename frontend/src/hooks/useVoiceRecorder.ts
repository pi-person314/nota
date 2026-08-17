import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderStatus = 'idle' | 'requesting-permission' | 'recording' | 'processing'

const MAX_DURATION_MS = 30_000

// RMS level (0-1, from getByteTimeDomainData) at or above which the
// musician is considered to be actively speaking.
const SPEECH_RMS_THRESHOLD = 0.03
// RMS level (0-1) at or below which the mic input is considered silent.
// Deliberately lower than SPEECH_RMS_THRESHOLD so there's a hysteresis band
// between the two that counts as neither speech nor silence.
const SILENCE_RMS_THRESHOLD = 0.015
// How long a continuous silent stretch has to last, once speech has already
// been heard during this recording, before it's auto-stopped (and sent).
const SILENCE_STOP_MS = 2000
// How long to wait for speech at all before auto-stopping a recording that
// has heard none since it began. Longer than SILENCE_STOP_MS so a musician
// who pauses to think isn't cut off before they've said anything. Downstream
// transcription handling already turns an empty/near-empty transcript into a
// "Didn't catch that — try again." notice, so no separate UI path is needed
// for this case.
const LEADING_SILENCE_STOP_MS = 6000

interface UseVoiceRecorderOptions {
  // Called once a recording finishes and is ready to send off — not called
  // when the recording was cancelled instead of stopped.
  onRecordingReady: (blob: Blob) => void | Promise<void>
  maxDurationMs?: number
  silenceStopMs?: number
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
  silenceStopMs = SILENCE_STOP_MS,
}: UseVoiceRecorderOptions): UseVoiceRecorderResult {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const maxTimerRef = useRef<number | null>(null)
  const discardRef = useRef(false)
  const onRecordingReadyRef = useRef(onRecordingReady)

  // Mic level monitoring, used to auto-stop the recording on silence.
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const levelIntervalRef = useRef<number | null>(null)
  const speechHeardRef = useRef(false)
  const silenceStartRef = useRef<number | null>(null)

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

  const stopLevelMonitoring = useCallback(() => {
    if (levelIntervalRef.current !== null) {
      window.clearInterval(levelIntervalRef.current)
      levelIntervalRef.current = null
    }
    const audioContext = audioContextRef.current
    audioContextRef.current = null
    analyserRef.current = null
    speechHeardRef.current = false
    silenceStartRef.current = null
    if (audioContext && audioContext.state !== 'closed') {
      void audioContext.close()
    }
  }, [])

  // Watches the mic level on the same stream MediaRecorder is using, purely
  // to detect silence — nothing here is connected to the audio destination,
  // so there's no playback. Failures are swallowed: if Web Audio isn't
  // available, recording still proceeds exactly as it would without
  // auto-stop, just without that feature.
  const startLevelMonitoring = useCallback((stream: MediaStream) => {
    try {
      const audioContext = new AudioContext()
      const source = audioContext.createMediaStreamSource(stream)
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      source.connect(analyser)
      // Recordings started hands-free (e.g. by the wake word) may have no
      // preceding user gesture, and a suspended context would silently
      // never report levels.
      void audioContext.resume()

      audioContextRef.current = audioContext
      analyserRef.current = analyser
      speechHeardRef.current = false
      silenceStartRef.current = null

      const buffer = new Uint8Array(analyser.fftSize)
      levelIntervalRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(buffer)
        let sumSquares = 0
        for (let i = 0; i < buffer.length; i++) {
          const normalized = buffer[i] / 128 - 1
          sumSquares += normalized * normalized
        }
        const rms = Math.sqrt(sumSquares / buffer.length)
        const now = Date.now()

        if (rms >= SPEECH_RMS_THRESHOLD) {
          speechHeardRef.current = true
          silenceStartRef.current = null
        } else if (rms <= SILENCE_RMS_THRESHOLD) {
          if (silenceStartRef.current === null) silenceStartRef.current = now
          const limit = speechHeardRef.current ? silenceStopMs : LEADING_SILENCE_STOP_MS
          if (now - silenceStartRef.current >= limit) {
            stop()
          }
        } else {
          // Hysteresis band between the two thresholds: not silence, but
          // not confidently speech either.
          silenceStartRef.current = null
        }
      }, 100)
    } catch {
      stopLevelMonitoring()
    }
  }, [silenceStopMs, stop, stopLevelMonitoring])

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
        stopLevelMonitoring()
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
      startLevelMonitoring(stream)
    } catch (err) {
      stopLevelMonitoring()
      releaseStream()
      setStatus('idle')
      const denied =
        err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')
      setError(denied ? 'Microphone access was denied.' : 'Could not access the microphone.')
    }
  }, [status, maxDurationMs, stop, startLevelMonitoring, stopLevelMonitoring])

  const finish = useCallback(() => {
    setStatus((current) => (current === 'processing' ? 'idle' : current))
  }, [])

  // Release the mic and any pending timer on unmount.
  useEffect(
    () => () => {
      clearMaxTimer()
      stopLevelMonitoring()
      releaseStream()
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== 'inactive') recorder.stop()
    },
    [stopLevelMonitoring],
  )

  return { status, error, start, stop, cancel, finish }
}
