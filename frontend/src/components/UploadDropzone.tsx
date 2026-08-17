import { useRef, useState } from 'react'
import { useScoreStore } from '../store/scoreStore'
import { UploadIcon } from './icons'

const ACCEPT = '.musicxml,.xml,.mxl,.pdf'

// Friendlier copy for the two OMR-specific error codes the backend can
// return for a PDF upload; every other error (including plain
// INVALID_MUSICXML from a PDF that converted but didn't parse) falls back
// to the server's own message, same as any other upload failure.
const OMR_ERROR_MESSAGES: Record<string, string> = {
  OMR_NOT_CONFIGURED: 'PDF import (beta) is not set up on this server yet.',
  OMR_FAILED: "Couldn't read this PDF as sheet music. Try a cleaner scan, or upload MusicXML instead.",
  OMR_LOW_QUALITY:
    "Couldn't get usable notation from this PDF. A clean, high-resolution scan of printed sheet music works best.",
}

interface UploadDropzoneProps {
  large?: boolean
  headline?: string
}

export function UploadDropzone({ large = false, headline = 'Drop a score here' }: UploadDropzoneProps) {
  const uploadScore = useScoreStore((s) => s.uploadScore)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [converting, setConverting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    setError(null)
    setNotice(null)
    setUploading(file.name)
    // PDF import runs OCR-based music recognition server-side, which takes
    // tens of seconds — a distinct label so this doesn't read as a stalled
    // upload of a small file.
    const isPdf = file.name.toLowerCase().endsWith('.pdf')
    setConverting(isPdf)
    const result = await uploadScore(file)
    setUploading(null)
    setConverting(false)
    if (inputRef.current) inputRef.current.value = ''
    if (!result.ok) {
      setError((result.code && OMR_ERROR_MESSAGES[result.code]) || result.message)
    } else if (isPdf && result.warnings?.length) {
      setNotice(`Imported with warnings: ${result.warnings.join(' ')}`)
    }
  }

  const active = dragOver ? 'border-pine text-pine' : 'border-ghost text-muted'

  return (
    <label
      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-card border-[1.5px] border-dashed transition-colors ${active} ${
        large ? 'min-h-64 p-12' : 'min-h-44 p-6'
      }`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        const file = e.dataTransfer.files?.[0]
        if (file) void handleFile(file)
      }}
    >
      <UploadIcon />
      {uploading ? (
        <>
          <div className="text-sm font-medium">{uploading}</div>
          {converting && (
            <div className="text-xs text-faint">Converting PDF to notation (beta) — this can take a minute…</div>
          )}
          <div className="upload-hairline w-40" />
        </>
      ) : (
        <>
          <div className={`font-medium ${large ? 'text-[15px]' : 'text-sm'}`}>{headline}</div>
          <div className="text-xs text-faint">MusicXML · .mxl · .xml · .pdf (beta) — or click to browse</div>
          {error && <div className="text-xs text-error">{error}</div>}
          {!error && notice && <div className="text-xs text-brass">{notice}</div>}
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
        }}
      />
    </label>
  )
}
