// Triggers a browser download of a score's canonical MusicXML straight from
// the backend's export endpoint (Content-Disposition: attachment), so no
// client-side file needs to be held in memory to export a score.
export function downloadScore(scoreId: string, fileName?: string) {
  const a = document.createElement('a')
  a.href = `/api/scores/${scoreId}/export`
  if (fileName) a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
}
