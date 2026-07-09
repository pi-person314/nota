import { useState, useEffect } from 'react'
import createVerovioModule from 'verovio/wasm'
import { VerovioToolkit } from 'verovio/esm'
import type { ScoreFormat } from '../store/scoreStore'

let toolkitPromise: Promise<VerovioToolkit> | null = null

export function getVerovioToolkit(): Promise<VerovioToolkit> {
  if (!toolkitPromise) {
    toolkitPromise = createVerovioModule().then((mod) => new VerovioToolkit(mod))
  }
  return toolkitPromise
}

export function loadScoreData(
  toolkit: VerovioToolkit,
  data: string | ArrayBuffer,
  format: ScoreFormat,
): boolean {
  if (format === 'mxl' && data instanceof ArrayBuffer) {
    return toolkit.loadZipDataBuffer(data)
  }
  return toolkit.loadData(data as string)
}

export async function renderThumbnail(
  data: string | ArrayBuffer,
  format: ScoreFormat,
): Promise<{ svg: string; pageCount: number } | null> {
  try {
    const toolkit = await getVerovioToolkit()
    toolkit.setOptions({
      pageWidth: 1800,
      scale: 40,
      adjustPageHeight: true,
      footer: 'none' as const,
      header: 'none' as const,
    })
    if (!loadScoreData(toolkit, data, format)) return null
    return { svg: toolkit.renderToSVG(1), pageCount: toolkit.getPageCount() }
  } catch {
    return null
  }
}

export function useVerovio() {
  const [toolkit, setToolkit] = useState<VerovioToolkit | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getVerovioToolkit()
      .then((tk) => {
        if (cancelled) return
        setToolkit(tk)
        setIsLoading(false)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setError(err.message)
        setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { toolkit, isLoading, error }
}
