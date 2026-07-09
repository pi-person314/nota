import { useState } from 'react'
import { MicIcon } from './icons'

const DEMO_HISTORY = ['cresc. bars 12–14', 'fermata, last note', 'mf at bar 9']
const DEMO_PARTIAL = '“now add a diminuendo at bar thirty—”'

export function VoiceBar() {
  const [listening, setListening] = useState(true)

  return (
    <div className="flex items-center gap-4.5 border-t border-line bg-bg px-7 pb-5.5 pt-4 max-md:flex-wrap">
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
      <div className="flex flex-1 flex-wrap justify-end gap-2">
        {DEMO_HISTORY.map((h) => (
          <button
            key={h}
            className="flex min-h-10 cursor-pointer items-center gap-1.75 rounded-pill border border-line bg-card px-3.25 py-1.75 font-sans text-[12.5px] text-muted hover:border-pine hover:text-pine"
            title="Scroll to this mark"
          >
            <span className="text-pine">✓</span>
            {h}
          </button>
        ))}
      </div>
    </div>
  )
}
