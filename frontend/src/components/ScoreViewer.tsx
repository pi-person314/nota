import { useEffect, useRef } from 'react'
import { useVerovio } from '../hooks/useVerovio'
import { useScoreStore } from '../store/scoreStore'

const VEROVIO_OPTIONS = {
  pageWidth: 2100,
  scale: 40,
  adjustPageHeight: true,
  footer: 'none' as const,
}

export function ScoreViewer() {
  const { toolkit, isLoading, error } = useVerovio()
  const containerRef = useRef<HTMLDivElement>(null)
  const { musicxml, currentPage, setTotalPages } = useScoreStore()

  useEffect(() => {
    if (!toolkit || !musicxml || !containerRef.current) return

    toolkit.setOptions(VEROVIO_OPTIONS)
    toolkit.loadData(musicxml)
    setTotalPages(toolkit.getPageCount())

    const svg = toolkit.renderToSVG(currentPage)
    containerRef.current.innerHTML = svg
  }, [toolkit, musicxml, currentPage, setTotalPages])

  if (error) {
    return <div className="text-red-500 p-8">Failed to load Verovio: {error}</div>
  }

  if (isLoading) {
    return <div className="text-gray-500 p-8">Loading Verovio...</div>
  }

  if (!musicxml) {
    return (
      <div className="text-gray-400 p-8 text-center">
        No score loaded. Upload a MusicXML file to get started.
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="w-full overflow-auto flex justify-center items-center"
    />
  )
}
