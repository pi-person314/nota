import { useCallback, useEffect, useRef, useState } from 'react'
import { useVerovio } from '../hooks/useVerovio'
import { useScoreStore } from '../store/scoreStore'

const SCALE = 40
const GAP = 16

export function ScoreViewer() {
  const { toolkit, isLoading, error } = useVerovio()
  const leftPageRef = useRef<HTMLDivElement>(null)
  const rightPageRef = useRef<HTMLDivElement>(null)
  const { musicxml, currentPage, setTotalPages } = useScoreStore()
  const [containerWidth, setContainerWidth] = useState(0)
  const observerRef = useRef<ResizeObserver | null>(null)

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect()
      observerRef.current = null
    }
    if (node) {
      const observer = new ResizeObserver((entries) => {
        setContainerWidth(entries[0].contentRect.width)
      })
      observer.observe(node)
      observerRef.current = observer
    }
  }, [])

  const renderPages = useCallback(() => {
    if (!toolkit || !musicxml || !leftPageRef.current || !rightPageRef.current || containerWidth === 0) return

    const pageWidth = Math.floor(((containerWidth - GAP) / 2) * (100 / SCALE))

    toolkit.setOptions({
      pageWidth,
      scale: SCALE,
      adjustPageHeight: true,
      footer: 'none' as const,
    })
    toolkit.loadData(musicxml)
    const pageCount = toolkit.getPageCount()
    setTotalPages(pageCount)

    leftPageRef.current.innerHTML = toolkit.renderToSVG(currentPage)

    const rightPage = currentPage + 1
    if (rightPage <= pageCount) {
      rightPageRef.current.innerHTML = toolkit.renderToSVG(rightPage)
      rightPageRef.current.style.display = ''
    } else {
      rightPageRef.current.innerHTML = ''
      rightPageRef.current.style.display = 'none'
    }
  }, [toolkit, musicxml, currentPage, containerWidth, setTotalPages])

  useEffect(() => {
    renderPages()
  }, [renderPages])

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
    <div ref={containerRef} className="w-full overflow-auto flex justify-center items-start gap-4">
      <div ref={leftPageRef} className="shrink-0" />
      <div ref={rightPageRef} className="shrink-0" />
    </div>
  )
}
