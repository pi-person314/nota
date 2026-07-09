interface ThumbnailProps {
  svg?: string
  caption?: string
  lines?: number
  className?: string
}

export function Thumbnail({ svg, caption, lines = 3, className = '' }: ThumbnailProps) {
  if (svg) {
    return (
      <div className={`score-svg overflow-hidden ${className}`}>
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      </div>
    )
  }
  return (
    <div className={`flex flex-col justify-between ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="staff-lines" />
      ))}
      {caption && (
        <div className="text-center font-mono text-[10px] text-ghost">{caption}</div>
      )}
    </div>
  )
}
