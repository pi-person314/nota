import { useWakeWordStore } from '../store/wakeWordStore'

// The wake word only actually runs while a score is open (that's where the
// command bar lives), so this reflects and toggles whether it's armed
// rather than claiming it is listening right now.
export function ListeningPill() {
  const armed = useWakeWordStore((s) => s.armed)
  const toggleArmed = useWakeWordStore((s) => s.toggleArmed)

  return (
    <button
      onClick={toggleArmed}
      aria-pressed={armed}
      className="flex min-h-10 cursor-pointer items-center gap-2 rounded-pill border-none bg-mist px-3.5 py-1.75 font-sans text-[13px] text-ink-soft"
      title={
        armed
          ? 'Wake word armed — listens for “Hey Nota” while a score is open'
          : 'Wake word off — turn it on to speak commands hands-free'
      }
    >
      <span className={`inline-block h-2 w-2 rounded-full ${armed ? 'bg-pine' : 'bg-ghost'}`} />
      {armed ? '“Hey Nota” armed' : 'Voice off'}
    </button>
  )
}
