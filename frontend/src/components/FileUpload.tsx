import { useScoreStore } from '../store/scoreStore'

export function FileUpload() {
  const setMusicXML = useScoreStore((s) => s.setMusicXML)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      const text = event.target?.result as string
      setMusicXML(text, file.name)
    }
    reader.readAsText(file)
  }

  return (
    <label className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 bg-nota-600 text-white rounded-lg hover:bg-nota-700 transition-colors shadow">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </svg>
      <span>Upload MusicXML</span>
      <input
        type="file"
        accept=".musicxml,.xml"
        onChange={handleFileChange}
        className="hidden"
      />
    </label>
  )
}
