import { useRef, useState } from 'react'
import { useScoreStore } from '../store/scoreStore'
import { UploadIcon } from './icons'

const ACCEPT = '.musicxml,.xml,.mxl,.pdf'

// Friendlier copy for the two OMR-specific error codes the backend can
// return for a PDF upload; every other error (including plain
// INVALID_MUSICXML from a PDF that converted but didn't parse) falls back
// to the server's own message, same as any other upload failure.
const OMR_ERROR_MESSAGES: Record<string, string> = {
  OMR_NOT_CONFIGURED: 'PDF import (experimental) is not set up on this server yet.',
  OMR_FAILED: "Couldn't read this PDF as sheet music. Try a cleaner scan, or upload MusicXML instead.",
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
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    setError(null)
    setUploading(file.name)
    // PDF import runs OCR-based music recognition server-side, which takes
    // tens of seconds — a distinct label so this doesn't read as a stalled
    // upload of a small file.
    setConverting(file.name.toLowerCase().endsWith('.pdf'))
    const result = await uploadScore(file)
    setUploading(null)
    setConverting(false)
    if (inputRef.current) inputRef.current.value = ''
    if (!result.ok) {
      setError((result.code && OMR_ERROR_MESSAGES[result.code]) || result.message)
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
            <div className="text-xs text-faint">Converting PDF to notation (experimental) — this can take a minute…</div>
          )}
          <div className="upload-hairline w-40" />
        </>
      ) : (
        <>
          <div className={`font-medium ${large ? 'text-[15px]' : 'text-sm'}`}>{headline}</div>
          <div className="text-xs text-faint">MusicXML · .mxl · .xml · .pdf (experimental) — or click to browse</div>
          {error && <div className="text-xs text-error">{error}</div>}
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
