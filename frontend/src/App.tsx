import { Header } from './components/Header'
import { Dashboard } from './components/Dashboard'
import { ScoreViewer } from './components/ScoreViewer'
import { PageNav } from './components/PageNav'
import { useScoreStore } from './store/scoreStore'

function App() {
  const musicxml = useScoreStore((s) => s.musicxml)

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <Header />
      {musicxml ? (
        <main className="flex-1 flex flex-col items-center p-4">
          <button
            onClick={() => useScoreStore.getState().clear()}
            className="self-start mb-2 px-3 py-1.5 text-sm text-nota-700 hover:text-nota-500 flex items-center gap-1 cursor-pointer"
          >
            ← Return to Dashboard
          </button>
          <ScoreViewer />
          <PageNav />
        </main>
      ) : (
        <Dashboard />
      )}
    </div>
  )
}

export default App
