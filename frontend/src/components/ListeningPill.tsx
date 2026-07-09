import { useScoreStore } from '../store/scoreStore'

export function ListeningPill() {
  const wakeEnabled = useScoreStore((s) => s.wakeEnabled)
  const toggleWake = useScoreStore((s) => s.toggleWake)

  return (
    <button
      onClick={toggleWake}
      aria-pressed={wakeEnabled}
      className="flex min-h-10 cursor-pointer items-center gap-2 rounded-pill border-none bg-mist px-3.5 py-1.75 font-sans text-[13px] text-ink-soft"
      title={wakeEnabled ? 'Turn wake-word off' : 'Turn wake-word on'}
    >
      <span
        className={`inline-block h-2 w-2 rounded-full ${wakeEnabled ? 'bg-pine' : 'bg-ghost'}`}
      />
      {wakeEnabled ? '“Hey Nota” is listening' : 'Voice off'}
    </button>
  )
}
