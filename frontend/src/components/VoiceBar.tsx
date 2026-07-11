import { useEffect, useRef, useState } from 'react'
import { MicIcon } from './icons'

const DEMO_PARTIAL = '“now add a diminuendo at bar thirty—”'

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
}

// The mic / "listening" affordance below is voice UI for a later phase —
// it stays visual-only (local toggle, no audio capture) and untouched by
// the typed-command wiring added here.
export function VoiceBar({
  history,
  busy,
  toast,
  clarification,
  onSubmitCommand,
  onUndo,
  onRedo,
}: VoiceBarProps) {
  const [listening, setListening] = useState(true)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (clarification) inputRef.current?.focus()
  }, [clarification])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    onSubmitCommand(text)
    setDraft('')
  }

  return (
    <div className="border-t border-line bg-bg">
      {(clarification || toast) && (
        <div
          className={`px-7 pt-3 font-mono text-[12.5px] ${
            clarification
              ? 'text-brass'
              : toast?.kind === 'error'
                ? 'text-error'
                : toast?.kind === 'notice'
                  ? 'text-muted'
                  : 'text-pine'
          }`}
        >
          {clarification ? `Nota asks: “${clarification}”` : toast?.text}
        </div>
      )}

      <div className="flex items-center gap-4.5 px-7 pb-2.5 pt-4 max-md:flex-wrap">
        <button
          aria-label={listening ? 'Stop listening' : 'Start listening'}
          aria-pressed={listening}
          onClick={() => setListening((l) => !l)}
          className={`flex h-13 w-13 shrink-0 cursor-pointer items-center justify-center rounded-full border-none text-on-pine ${
            listening
              ? 'mic-pulse bg-[radial-gradient(circle_at_35%_30%,var(--mic-hi),var(--mic-lo))]'
              : 'bg-ghost'
          }`}
        >
          <MicIcon />
        </button>
        <div className="min-w-0 md:min-w-75">
          {listening ? (
            <>
              <div className="text-[13.5px] font-semibold text-pine">Listening…</div>
              <div className="mt-0.75 truncate font-mono text-[12.5px] italic text-ink-soft">
                {DEMO_PARTIAL}
              </div>
            </>
          ) : (
            <>
              <div className="text-[13.5px] font-semibold text-muted">Voice off</div>
              <div className="mt-0.75 font-mono text-[12.5px] text-ghost">
                tap the mic or say “Hey Nota”
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
        </div>
        {history.length > 0 && (
          <div className="flex flex-1 flex-wrap justify-end gap-2">
            {history.map((h, i) => (
              <span
                key={i}
                className="flex min-h-10 items-center gap-1.75 rounded-pill border border-line bg-card px-3.25 py-1.75 font-sans text-[12.5px] text-muted"
              >
                <span className="text-pine">✓</span>
                {h}
              </span>
            ))}
          </div>
        )}
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
