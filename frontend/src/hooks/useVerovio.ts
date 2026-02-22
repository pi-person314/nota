import { useState, useEffect, useRef } from 'react'
import createVerovioModule from 'verovio/wasm'
import { VerovioToolkit } from 'verovio/esm'

export function useVerovio() {
  const [toolkit, setToolkit] = useState<VerovioToolkit | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const initRef = useRef(false)

  useEffect(() => {
    if (initRef.current) return
    initRef.current = true

    createVerovioModule()
      .then((VerovioModule) => {
        const tk = new VerovioToolkit(VerovioModule)
        setToolkit(tk)
        setIsLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setIsLoading(false)
      })
  }, [])

  return { toolkit, isLoading, error }
}
