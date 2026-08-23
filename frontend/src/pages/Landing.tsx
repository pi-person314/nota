import { Link, useNavigate } from 'react-router-dom'
import { MicIcon } from '../components/icons'

const STEPS = [
  {
    num: '01',
    title: 'Upload your score',
    body: 'Drop in any MusicXML file — exported from Sibelius, MuseScore, Finale, or scanned and converted.',
  },
  {
    num: '02',
    title: 'Say the marking',
    body: '“Add a fermata on the last note.” “Forte at bar nine.” Natural musical language, no syntax.',
  },
  {
    num: '03',
    title: 'Watch it land',
    body: 'The notation appears on the engraved score instantly, and exports back to MusicXML.',
  },
]

const PHRASES = [
  { text: 'add a crescendo from bar 5 to bar 8', side: 'self-start' },
  { text: 'staccato on beats one and two, bar twenty-one', side: 'self-end' },
  { text: 'pianissimo at the double bar', side: 'self-start' },
]

function DemoStaff({ className = '' }: { className?: string }) {
  return (
    <div
      className={`h-6 bg-[repeating-linear-gradient(180deg,var(--ghost)_0_1px,transparent_1px_6px)] bg-size-[100%_24px] bg-no-repeat ${className}`}
    />
  )
}

export function Landing() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-bg">
      <div className="flex items-center justify-between border-b border-line px-12 py-5 max-md:px-6">
        <span className="font-display text-2xl text-ink">Nota</span>
        <div className="flex items-center gap-3">
          <Link
            to="/login"
            className="px-4.5 py-2.5 text-sm font-medium text-ink no-underline hover:text-pine"
          >
            Log in
          </Link>
          <Link
            to="/signup"
            className="rounded-pill bg-pine px-5 py-2.5 text-sm font-medium text-on-pine no-underline hover:bg-pine-deep"
          >
            Sign up
          </Link>
        </div>
      </div>

      <div className="rise mx-auto grid max-w-310 grid-cols-[1.1fr_1fr] items-center gap-16 px-12 pb-18 pt-21 max-lg:grid-cols-1 max-md:px-6">
        <div>
          <div className="mb-5 font-mono text-[12.5px] tracking-[0.14em] text-pine">
            FOR MUSICIANS WHOSE HANDS ARE BUSY
          </div>
          <h1 className="m-0 font-display text-[58px] font-normal leading-[1.08] text-ink max-md:text-[44px]">
            Your voice,
            <br />
            on the page.
          </h1>
          <p className="mb-0 mt-6 max-w-110 text-[17px] leading-relaxed text-muted">
            Say “crescendo from bar twelve” and watch it land on your score. Nota annotates
            sheet music while your hands stay on your instrument.
          </p>
          <div className="mt-9 flex items-center gap-5">
            <button
              onClick={() => navigate('/signup')}
              className="cursor-pointer rounded-pill border-none bg-pine px-7.5 py-3.75 font-sans text-[15px] font-semibold text-on-pine hover:bg-pine-deep"
            >
              Get started — it’s free
            </button>
            <a
              href="#how"
              className="border-b border-ghost pb-0.5 text-sm font-medium text-pine no-underline hover:text-brass"
            >
              How it works
            </a>
          </div>
        </div>

        <div className="rounded-card border border-line bg-card px-8 pb-6 pt-8 shadow-[0_12px_40px_rgba(34,48,31,0.10)]">
          <div className="mb-6 flex items-center gap-2.5">
            <div className="flex h-8.5 w-8.5 shrink-0 items-center justify-center rounded-full bg-pine text-on-pine">
              <MicIcon size={14} />
            </div>
            <div className="font-mono text-[13px] italic text-ink-soft">
              “crescendo from bar twelve to fourteen”
            </div>
          </div>
          <div className="flex flex-col gap-5">
            <DemoStaff />
            <div className="relative">
              <DemoStaff />
              <div className="absolute -top-2 -bottom-3.5 left-[18%] right-[30%] rounded-[3px] bg-pine/8" />
              <div className="demo-sweep absolute left-[18%] top-8.5 h-0.5 max-w-[52%] bg-pine" />
              <div className="demo-chip absolute left-[18%] top-11 font-mono text-[11px] text-pine">
                cresc. — bars 12–14 ✓
              </div>
            </div>
            <DemoStaff className="mt-5.5" />
          </div>
          <div className="mt-5.5 text-center font-mono text-[10px] text-ghost">
            live verovio render of your score
          </div>
        </div>
      </div>

      <div id="how" className="border-t border-line bg-card">
        <div className="mx-auto grid max-w-310 grid-cols-3 gap-12 px-12 py-18 max-md:grid-cols-1 max-md:px-6">
          {STEPS.map((st) => (
            <div key={st.num}>
              <div className="font-display text-[44px] text-brass">{st.num}</div>
              <div className="mt-3 font-display text-[21px] text-ink">{st.title}</div>
              <div className="mt-2 text-[14.5px] leading-relaxed text-muted">{st.body}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="mx-auto flex max-w-310 flex-col gap-16 px-12 py-18 max-md:px-6">
        <div className="grid grid-cols-2 items-center gap-16 max-md:grid-cols-1">
          <div>
            <div className="font-display text-[30px] leading-tight text-ink">
              It speaks musician.
            </div>
            <p className="mb-0 mt-3.5 max-w-105 text-[15.5px] leading-relaxed text-muted">
              Bars, beats, dynamics, articulations, fingerings — say them the way you'd say them
              to a stand partner. No command syntax to memorize.
            </p>
          </div>
          <div className="flex flex-col gap-3 rounded-card bg-tint p-7">
            {PHRASES.map((ph) => (
              <div
                key={ph.text}
                className={`rounded-pill border border-line bg-card px-4.5 py-2.5 text-sm text-ink-soft ${ph.side}`}
              >
                “{ph.text}”
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 items-center gap-16 max-md:grid-cols-1">
          <div className="rounded-card bg-ink p-10 text-bg max-md:order-2">
            <div className="flex items-center gap-3">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-[#7FAE93]" />
              <span className="font-mono text-[13px] text-[#A8C4B2]">
                hands-free · “Hey Nota”
              </span>
            </div>
            <div className="mt-4 font-display text-[23px] leading-snug">
              Bow in one hand,
              <br />
              pencil in neither.
            </div>
          </div>
          <div className="max-md:order-1">
            <div className="font-display text-[30px] leading-tight text-ink">
              Wake it with a word.
            </div>
            <p className="mb-0 mt-3.5 max-w-105 text-[15.5px] leading-relaxed text-muted">
              Nota waits quietly until you say “Hey Nota.” Mark a passage mid-rehearsal without
              putting your instrument down — the score updates instantly, and exports as
              standard MusicXML.
            </p>
          </div>
        </div>
      </div>

      <div className="border-t border-line">
        <div className="mx-auto flex max-w-310 items-baseline justify-between px-12 py-7 max-md:px-6">
          <span className="font-display text-base text-ink">Nota</span>
          <span className="flex items-baseline gap-5 text-[13px] text-faint">
            <Link to="/privacy" className="text-faint no-underline hover:text-pine">
              Privacy
            </Link>
            Built for musicians, by musicians. © 2026
          </span>
        </div>
      </div>
    </div>
  )
}
