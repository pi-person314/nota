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
