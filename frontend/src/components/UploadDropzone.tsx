import { useRef, useState } from 'react'
import { useScoreStore, type ScoreFormat } from '../store/scoreStore'
import { renderThumbnail } from '../hooks/useVerovio'
import { UploadIcon } from './icons'

const ACCEPT = '.musicxml,.xml,.mxl'

function titleFromFileName(name: string): string {
  return name.replace(/\.(musicxml|xml|mxl)$/i, '')
}

interface UploadDropzoneProps {
  large?: boolean
  headline?: string
}

export function UploadDropzone({ large = false, headline = 'Drop a score here' }: UploadDropzoneProps) {
  const addScore = useScoreStore((s) => s.addScore)
  const updateScore = useScoreStore((s) => s.updateScore)
  const removeScore = useScoreStore((s) => s.removeScore)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    const format: ScoreFormat = /\.mxl$/i.test(file.name) ? 'mxl' : 'xml'
    setError(null)
    setUploading(file.name)
    const id = addScore({
      title: titleFromFileName(file.name),
      starred: false,
      marks: 0,
      pending: true,
      fileName: file.name,
      format,
    })
    try {
      const data = format === 'mxl' ? await file.arrayBuffer() : await file.text()
      const rendered = await renderThumbnail(data, format)
      if (!rendered) {
        removeScore(id)
        setError(`Couldn't read ${file.name} — is it valid MusicXML?`)
        return
      }
      updateScore(id, {
        data,
        thumbnail: rendered.svg,
        totalPages: rendered.pageCount,
        pending: false,
        modifiedAt: Date.now(),
      })
    } catch {
      removeScore(id)
      setError(`Couldn't read ${file.name} — is it valid MusicXML?`)
    } finally {
      setUploading(null)
      if (inputRef.current) inputRef.current.value = ''
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
          <div className="upload-hairline w-40" />
        </>
      ) : (
        <>
          <div className={`font-medium ${large ? 'text-[15px]' : 'text-sm'}`}>{headline}</div>
          <div className="text-xs text-faint">MusicXML · .mxl · .xml — or click to browse</div>
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
