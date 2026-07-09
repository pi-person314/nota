import type { Score } from '../store/scoreStore'

export function downloadScore(score: Score) {
  if (!score.data) return
  const blob =
    typeof score.data === 'string'
      ? new Blob([score.data], { type: 'application/vnd.recordare.musicxml+xml' })
      : new Blob([score.data], { type: 'application/vnd.recordare.musicxml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = score.fileName ?? `${score.title}.musicxml`
  a.click()
  URL.revokeObjectURL(url)
}
