import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  MicIcon,
  SpeakerIcon,
  SpeakerMuteIcon,
  WakeWordIcon,
  WakeWordOffIcon,
} from './icons'
import { api, ApiRequestError } from '../lib/api'
import { useVoiceRecorder } from '../hooks/useVoiceRecorder'
import { useWakeWord } from '../hooks/useWakeWord'
import { useReadbackStore } from '../store/readbackStore'
import { useWakeWordStore } from '../store/wakeWordStore'

export interface CommandToast {
  kind: 'confirmation' | 'notice' | 'error'
  text: string
}

interface VoiceBarProps {
  history: string[]
  busy: boolean
  toast: CommandToast | null
  clarification: string | null
  onSubmitCommand: (text: string) => void
  onUndo: () => void
  onRedo: () => void
  onVoiceMessage: (toast: CommandToast) => void
  // Bumped by the parent whenever a command comes back needing clarification
  // for the first time in a row — the mic re-arms itself so the musician can
  // answer hands-free.
  voiceRearmToken: number
  // Bumped by the parent when a *second* consecutive clarification arrives —
  // guards against re-arm loops by cutting the mic and handing off to text.
  voiceStandDownToken: number
  // Called whenever the musician manually (re)starts the mic, so any
  // readback still playing gets cut off before it can bleed into the
  // recording.
  onManualRecordStart: () => void
  // Whether Nota is currently speaking a reply aloud — the wake word
  // listener is suspended for the duration so it can't hear itself.
  ttsSpeaking: boolean
}

// Shortest transcript worth sending to the command endpoint. Anything
// shorter is almost certainly silence or noise; the backend would just
// bounce it with EMPTY_TRANSCRIPT, so it's handled here instead.
const MIN_TRANSCRIPT_LENGTH = 2

const COLLAPSED_STORAGE_KEY = 'nota-voicebar-collapsed'

function initialCollapsed(): boolean {
  return localStorage.getItem(COLLAPSED_STORAGE_KEY) === 'true'
}

export function VoiceBar({
  history,
  busy,
  toast,
  clarification,
  onSubmitCommand,
  onUndo,
  onRedo,
  onVoiceMessage,
  voiceRearmToken,
  voiceStandDownToken,
  onManualRecordStart,
  ttsSpeaking,
}: VoiceBarProps) {
  const [draft, setDraft] = useState('')
  const [retryable, setRetryable] = useState(false)
  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const inputRef = useRef<HTMLInputElement>(null)
  const readbackMuted = useReadbackStore((s) => s.muted)
  const toggleReadbackMuted = useReadbackStore((s) => s.toggleMuted)
  const wakeWordArmed = useWakeWordStore((s) => s.armed)
  const toggleWakeWordArmed = useWakeWordStore((s) => s.toggleArmed)

  const handleRecordingReady = useCallback(
    async (blob: Blob) => {
      try {
        const { text } = await api.transcribeAudio(blob)
        const trimmed = text.trim()
        if (trimmed.length < MIN_TRANSCRIPT_LENGTH) {
          setRetryable(true)
          onVoiceMessage({ kind: 'notice', text: 'Didn’t catch that — try again.' })
          return
        }
        setRetryable(false)
        setDraft(trimmed)
        onSubmitCommand(trimmed)
      } catch (err) {
        if (err instanceof ApiRequestError && err.code === 'STT_NOT_CONFIGURED') {
          setRetryable(false)
          onVoiceMessage({ kind: 'notice', text: 'Voice transcription isn’t configured on this server.' })
          inputRef.current?.focus()
        } else if (err instanceof ApiRequestError && (err.code === 'TRANSCRIPTION_FAILED' || err.code === 'NO_AUDIO')) {
          setRetryable(true)
          onVoiceMessage({ kind: 'notice', text: 'Didn’t catch that — try again.' })
        } else {
          setRetryable(true)
          onVoiceMessage({
            kind: 'error',
            text: err instanceof Error ? err.message : 'Voice transcription failed.',
          })
        }
      } finally {
        recorderRef.current.finish()
      }
    },
    [onSubmitCommand, onVoiceMessage],
  )

  const recorder = useVoiceRecorder({ onRecordingReady: handleRecordingReady })
  const recorderRef = useRef(recorder)
  recorderRef.current = recorder

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      const next = !c
      localStorage.setItem(COLLAPSED_STORAGE_KEY, String(next))
      return next
    })
  }, [])

  // Bring the panel back into view whenever the musician's attention is
  // needed: a clarifying question just arrived, or a recording just started
  // (including one triggered hands-free by the wake word while collapsed).
  // Scoped to these two signals only, so a manual collapse mid-conversation
  // isn't immediately undone by this effect re-running for unrelated reasons.
  useEffect(() => {
    if (clarification !== null || recorder.status !== 'idle') {
      setCollapsed(false)
      localStorage.setItem(COLLAPSED_STORAGE_KEY, 'false')
    }
  }, [clarification, recorder.status])

  // Depends on `collapsed` too: when a clarification triggers auto-expand,
  // the input doesn't exist in the DOM until the expand takes effect, so
  // this needs to re-run once `collapsed` flips to false.
  useEffect(() => {
    if (clarification && !collapsed) inputRef.current?.focus()
  }, [clarification, collapsed])

  // Surface permission / support errors from the recorder through the same
  // toast the rest of the voice pipeline uses.
  const lastRecorderError = useRef<string | null>(null)
  useEffect(() => {
    if (recorder.error && recorder.error !== lastRecorderError.current) {
      onVoiceMessage({ kind: 'error', text: recorder.error })
    }
    lastRecorderError.current = recorder.error
  }, [recorder.error, onVoiceMessage])

  // Auto re-arm the mic for a hands-free answer to a clarifying question —
  // but only the first time in a row (see voiceStandDownToken below).
  const lastRearmToken = useRef(0)
  useEffect(() => {
    if (voiceRearmToken !== lastRearmToken.current) {
      lastRearmToken.current = voiceRearmToken
      if (voiceRearmToken > 0) {
        setRetryable(false)
        void recorderRef.current.start()
      }
    }
  }, [voiceRearmToken])

  // A second consecutive clarification: stop guessing, cut the mic, and let
  // the musician answer by typing instead.
  const lastStandDownToken = useRef(0)
  useEffect(() => {
    if (voiceStandDownToken !== lastStandDownToken.current) {
      lastStandDownToken.current = voiceStandDownToken
      if (voiceStandDownToken > 0) {
        recorderRef.current.cancel()
        inputRef.current?.focus()
      }
    }
  }, [voiceStandDownToken])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setRetryable(false)
    onSubmitCommand(text)
    setDraft('')
  }

  const micDisabled = busy || recorder.status === 'requesting-permission' || recorder.status === 'processing'

  const handleMicClick = () => {
    if (recorder.status === 'recording') {
      recorder.stop()
    } else if (recorder.status === 'idle') {
      onManualRecordStart()
      setRetryable(false)
      void recorder.start()
    }
  }

  const handleRetry = () => {
    onManualRecordStart()
    setRetryable(false)
    void recorder.start()
  }

  // Detection fires the exact same start path as tapping the mic button
  // does — cutting off any readback in flight, then recording. Guarded
  // against races where a stale detection lands after the mic already
  // stopped being idle (e.g. it fires just as a command finishes coming in).
  const handleWakeWord = useCallback(() => {
    if (recorderRef.current.status !== 'idle') return
    onManualRecordStart()
    setRetryable(false)
    void recorderRef.current.start()
  }, [onManualRecordStart])

  // Suspended (not torn down) whenever Nota is talking or already listening
  // for a command, so it can't trigger on its own voice or double-start a
  // recording.
  const wakeWordEnabled = wakeWordArmed && !ttsSpeaking && !busy && recorder.status === 'idle'
  const { available: wakeWordAvailable, listening: wakeWordListening } = useWakeWord({
    enabled: wakeWordEnabled,
    onWake: handleWakeWord,
  })

  const micLabel =
    recorder.status === 'recording'
      ? 'Stop listening'
      : recorder.status === 'requesting-permission'
        ? 'Requesting microphone access'
        : recorder.status === 'processing'
          ? 'Transcribing'
          : 'Start listening'

  // Same text/color the expanded toast line uses, plus a fallback hint for
  // when the panel is collapsed and there's nothing to report.
  const statusText = clarification
    ? `Nota asks: “${clarification}”`
    : toast
      ? toast.text
      : 'command panel hidden — say “Hey Nota” or expand to type'

  const statusColor = clarification
    ? 'text-brass'
    : toast?.kind === 'error'
      ? 'text-error'
      : toast?.kind === 'notice'
        ? 'text-muted'
        : toast?.kind === 'confirmation'
          ? 'text-pine'
          : 'text-ghost'

  if (collapsed) {
    return (
      <div className="border-t border-line bg-bg">
        <div className="flex items-center justify-between gap-3 px-7 py-2.5">
          <span className={`truncate font-mono text-[12.5px] ${statusColor}`}>{statusText}</span>
          <button
            aria-label="Show command panel"
            onClick={toggleCollapsed}
            className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-pill border border-line bg-transparent text-muted hover:border-pine hover:text-pine"
          >
            <ChevronUpIcon />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="border-t border-line bg-bg">
      {(clarification || toast) && (
        <div
          className={`flex items-center gap-3 px-7 pt-3 font-mono text-[12.5px] ${
            clarification
              ? 'text-brass'
              : toast?.kind === 'error'
                ? 'text-error'
                : toast?.kind === 'notice'
                  ? 'text-muted'
                  : 'text-pine'
          }`}
        >
          <span>{clarification ? `Nota asks: “${clarification}”` : toast?.text}</span>
          {!clarification && retryable && (
            <button
              onClick={handleRetry}
              className="cursor-pointer whitespace-nowrap border-none bg-transparent p-0 font-mono text-[12.5px] text-pine underline hover:text-pine-deep"
            >
              record again
            </button>
          )}
        </div>
      )}

      <div className="flex items-center gap-4.5 px-7 pb-2.5 pt-4 max-md:flex-wrap">
        <button
          aria-label={micLabel}
          aria-pressed={recorder.status === 'recording'}
          onClick={handleMicClick}
          disabled={micDisabled}
          className={`flex h-13 w-13 shrink-0 cursor-pointer items-center justify-center rounded-full border-none text-on-pine disabled:cursor-default ${
            recorder.status === 'recording'
              ? 'mic-pulse bg-[radial-gradient(circle_at_35%_30%,var(--mic-hi),var(--mic-lo))]'
              : recorder.status === 'processing' || recorder.status === 'requesting-permission'
                ? 'bg-brass'
                : 'bg-ghost'
          }`}
        >
          <MicIcon />
        </button>
        <div className="min-w-0 md:min-w-75">
          {recorder.status === 'recording' ? (
            <>
              <div className="text-[13.5px] font-semibold text-pine">Listening…</div>
              <div className="mt-0.75 flex items-center gap-2 font-mono text-[12.5px] text-ink-soft">
                <span>tap the mic to stop and send</span>
                <button
                  onClick={() => recorder.cancel()}
                  className="cursor-pointer whitespace-nowrap border-none bg-transparent p-0 text-ghost underline hover:text-error"
                >
                  cancel
                </button>
              </div>
            </>
          ) : recorder.status === 'requesting-permission' ? (
            <>
              <div className="text-[13.5px] font-semibold text-brass">Requesting mic access…</div>
              <div className="mt-0.75 font-mono text-[12.5px] text-ghost">check your browser’s permission prompt</div>
            </>
          ) : recorder.status === 'processing' ? (
            <>
              <div className="text-[13.5px] font-semibold text-brass">Transcribing…</div>
              <div className="mt-0.75 font-mono text-[12.5px] text-ghost">sending your recording</div>
            </>
          ) : (
            <>
              <div className="text-[13.5px] font-semibold text-muted">Voice off</div>
              <div className="mt-0.75 font-mono text-[12.5px] text-ghost">
                tap the mic to speak a command — or say “Hey Nota” ({wakeWordAvailable && wakeWordArmed ? 'on' : 'off'})
              </div>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onUndo}
            className="min-h-9 cursor-pointer whitespace-nowrap rounded-pill border border-line bg-transparent px-3.5 py-1.5 font-sans text-[12.5px] text-muted hover:border-pine hover:text-pine"
          >
            Undo
          </button>
          <button
            onClick={onRedo}
            className="min-h-9 cursor-pointer whitespace-nowrap rounded-pill border border-line bg-transparent px-3.5 py-1.5 font-sans text-[12.5px] text-muted hover:border-pine hover:text-pine"
          >
            Redo
          </button>
          <button
            aria-label={readbackMuted ? 'Unmute spoken replies' : 'Mute spoken replies'}
            aria-pressed={readbackMuted}
            title={readbackMuted ? 'Turn readback on' : 'Turn readback off'}
            onClick={toggleReadbackMuted}
            className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-pill border border-line bg-transparent text-muted hover:border-pine hover:text-pine"
          >
            {readbackMuted ? <SpeakerMuteIcon /> : <SpeakerIcon />}
          </button>
          <button
            aria-label={wakeWordArmed ? 'Disarm "Hey Nota" wake word' : 'Arm "Hey Nota" wake word'}
            aria-pressed={wakeWordArmed}
            title={
              !wakeWordAvailable
                ? 'Wake word needs setup: openWakeWord model files in the public directory'
                : wakeWordArmed
                  ? wakeWordListening
                    ? 'Listening for "Hey Nota" — click to disarm'
                    : 'Armed for "Hey Nota" — click to disarm'
                  : 'Click to arm hands-free "Hey Nota" listening'
            }
            disabled={!wakeWordAvailable}
            onClick={toggleWakeWordArmed}
            className={`flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-pill px-3.5 py-1.5 font-sans text-[12.5px] disabled:cursor-default disabled:opacity-40 disabled:hover:border-line disabled:hover:text-muted ${
              wakeWordArmed && wakeWordAvailable
                ? 'border border-transparent bg-pine text-on-pine hover:bg-pine-deep'
                : 'border border-line bg-transparent text-muted hover:border-pine hover:text-pine'
            }`}
          >
            {wakeWordArmed && wakeWordAvailable ? <WakeWordIcon /> : <WakeWordOffIcon />}
            <span>“Hey Nota”</span>
          </button>
        </div>
        <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
          {history.map((h, i) => (
            <span
              key={i}
              className="flex min-h-10 items-center gap-1.75 rounded-pill border border-line bg-card px-3.25 py-1.75 font-sans text-[12.5px] text-muted"
            >
              <span className="text-pine">✓</span>
              {h}
            </span>
          ))}
          <button
            aria-label="Hide command panel"
            onClick={toggleCollapsed}
            className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-pill border border-line bg-transparent text-muted hover:border-pine hover:text-pine"
          >
            <ChevronDownIcon />
          </button>
        </div>
      </div>

      <form onSubmit={submit} className="flex items-center gap-2.5 px-7 pb-5.5">
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={clarification ?? 'Type a command — “forte at measure 12”'}
          disabled={busy}
          className="nota-input min-w-0 flex-1 rounded-pill border border-line bg-card px-4 py-2.25 font-mono text-[12.5px] text-ink"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="min-h-9.5 shrink-0 cursor-pointer whitespace-nowrap rounded-pill border-none bg-pine px-4.5 py-2 font-sans text-[12.5px] font-semibold text-on-pine hover:bg-pine-deep disabled:cursor-default disabled:bg-ghost"
        >
          {busy ? 'Working…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
