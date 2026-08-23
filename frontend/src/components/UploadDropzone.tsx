import { useRef, useState } from 'react'
import { useScoreStore } from '../store/scoreStore'
import { UploadIcon } from './icons'

const ACCEPT = '.musicxml,.xml,.mxl,.pdf'

// Friendlier copy for the OMR-specific and job-lifecycle error codes the
// backend can return for a PDF upload; every other error (including
// plain INVALID_MUSICXML from a PDF that converted but didn't parse)
// falls back to the server's own message, same as any other upload
// failure.
const OMR_ERROR_MESSAGES: Record<string, string> = {
  OMR_NOT_CONFIGURED: 'PDF import (beta) is not set up on this server yet.',
  OMR_FAILED: "Couldn't read this PDF as sheet music. Try a cleaner scan, or upload MusicXML instead.",
  OMR_LOW_QUALITY:
    "Couldn't get usable notation from this PDF. A clean, high-resolution scan of printed sheet music works best.",
  SERVER_RESTARTED: 'The server restarted mid-conversion — please try again.',
  TOO_MANY_CONVERSIONS: 'Too many conversions are already in progress — please wait for one to finish and try again.',
}

interface UploadDropzoneProps {
  large?: boolean
  headline?: string
}

function jobErrorMessage(job: { error_code: string | null; error_message: string | null }): string {
  return (job.error_code && OMR_ERROR_MESSAGES[job.error_code]) || job.error_message || 'PDF conversion failed.'
}

export function UploadDropzone({ large = false, headline = 'Drop a score here' }: UploadDropzoneProps) {
  const uploadScore = useScoreStore((s) => s.uploadScore)
  const clearConversion = useScoreStore((s) => s.clearConversion)
  // Any conversion still queued/running, regardless of which page load
  // started it — reading it straight from the store (rather than only
  // tracking one this component instance itself kicked off) is what lets
  // the indicator survive navigating away and back: resumeConversions()
  // repopulates this on the next dashboard mount.
  const activeConversion = useScoreStore((s) =>
    s.conversions.find((c) => c.status === 'queued' || c.status === 'running'),
  )

  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // The finished state of a job *this* dropzone submitted, so its outcome
  // (warnings or an error) can be shown once — read live off the store so
  // it updates the moment polling resolves it.
  const finishedConversion = useScoreStore((s) =>
    jobId ? s.conversions.find((c) => c.id === jobId && c.status !== 'queued' && c.status !== 'running') : undefined,
  )

  const handleFile = async (file: File) => {
    setError(null)
    setNotice(null)
    if (jobId) {
      // Drop the previous attempt's finished job (if any) so its outcome
      // doesn't linger once a new upload is underway.
      clearConversion(jobId)
      setJobId(null)
    }
    setUploading(file.name)
    const result = await uploadScore(file)
    setUploading(null)
    if (inputRef.current) inputRef.current.value = ''
    if (!result.ok) {
      setError((result.code && OMR_ERROR_MESSAGES[result.code]) || result.message)
      return
    }
    if ('jobId' in result) {
      setJobId(result.jobId)
      return
    }
    if (result.warnings?.length) {
      setNotice(`Imported with warnings: ${result.warnings.join(' ')}`)
    }
  }

  const jobError = finishedConversion?.status === 'failed' ? jobErrorMessage(finishedConversion) : null
  const jobNotice =
    finishedConversion?.status === 'succeeded' && finishedConversion.warnings.length
      ? `Imported with warnings: ${finishedConversion.warnings.join(' ')}`
      : null
  const displayError = error ?? jobError
  const displayNotice = displayError ? null : (notice ?? jobNotice)

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
          <div className="upload-hairline w-40" />
        </>
      ) : activeConversion ? (
        <>
          <div className="text-sm font-medium">{activeConversion.filename}</div>
          <div className="text-xs text-faint">
            {activeConversion.status === 'queued'
              ? "Queued behind another conversion — converting PDF to notation (beta) once it's your turn…"
              : 'Converting PDF to notation (beta) — this can take a minute…'}
          </div>
          <div className="upload-hairline w-40" />
        </>
      ) : (
        <>
          <div className={`font-medium ${large ? 'text-[15px]' : 'text-sm'}`}>{headline}</div>
          <div className="text-xs text-faint">MusicXML · .mxl · .xml · .pdf (beta) — or click to browse</div>
          {displayError && <div className="text-xs text-error">{displayError}</div>}
          {displayNotice && <div className="text-xs text-brass">{displayNotice}</div>}
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
