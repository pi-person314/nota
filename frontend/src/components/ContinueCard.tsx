import { useNavigate } from 'react-router-dom'
import { useScoreStore, type Score } from '../store/scoreStore'
import { Thumbnail } from './Thumbnail'

export function ContinueCard({ score }: { score: Score }) {
  const markOpened = useScoreStore((s) => s.markOpened)
  const navigate = useNavigate()

  const meta = [
    score.composer,
    score.part,
    score.totalPages ? `page ${score.lastPage} of ${score.totalPages}` : undefined,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div
      className="flex cursor-pointer items-center gap-7 rounded-card border border-line bg-card px-7 py-6 transition-shadow hover:shadow-bloom max-md:flex-col max-md:items-start"
      onClick={() => {
        markOpened(score.id)
        navigate(`/score/${score.id}`)
      }}
      role="link"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          markOpened(score.id)
          navigate(`/score/${score.id}`)
        }
      }}
    >
      <div className="flex-1">
        <div className="mb-2.5 text-xs tracking-[0.08em] text-faint">CONTINUE</div>
        <div className="flex items-center gap-2">
          <div className="font-display text-2xl text-ink">{score.title}</div>
          {score.fromPdf && (
            <span
              title="Converted from a PDF — recognition is not 100% reliable, so check this score against the original."
              className="rounded-pill border border-line px-1.5 font-mono text-[10px] text-brass"
            >
              PDF
            </span>
          )}
        </div>
        {meta && <div className="mt-1 text-sm text-muted">{meta}</div>}
        {score.lastSaid && (
          <div className="mt-4 inline-flex items-center gap-2 rounded-input bg-tint px-3 py-2 text-[13px] text-ink-soft">
            <span className="font-mono text-xs text-pine">last said</span>
            <span className="font-mono italic">“{score.lastSaid}”</span>
          </div>
        )}
      </div>
      <Thumbnail
        svg={score.thumbnail}
        caption="preview unavailable"
        className="h-35 w-55 shrink-0 rounded-[3px] border border-line-faint bg-card px-4 py-4.5 max-md:w-full"
      />
    </div>
  )
}
