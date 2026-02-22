import { FileUpload } from './components/FileUpload'
import { ScoreViewer } from './components/ScoreViewer'
import { PageNav } from './components/PageNav'
import { useScoreStore } from './store/scoreStore'

function App() {
  const fileName = useScoreStore((s) => s.fileName)

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="border-b bg-nota-100 border-nota-200 px-6 py-3 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-nota-900">Nota</h1>
        <FileUpload />
      </header>
      <main className="flex-1 flex flex-col items-center p-4">
        {fileName && (
          <p className="text-sm text-gray-500 mb-2">{fileName}</p>
        )}
        <ScoreViewer />
        <PageNav />
      </main>
    </div>
  )
}

export default App
