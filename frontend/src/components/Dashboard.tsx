import { useState } from 'react'
import { ScoreCard } from './ScoreCard'
import { useScoreStore } from '../store/scoreStore'

const MOCK_SCORES = [
  { title: 'Beethoven Symphony No. 5', opened: 'Today', modified: 'Yesterday', starred: true },
  { title: 'My Composition Draft', opened: 'Today', modified: 'Today', starred: false },
  { title: 'Mozart Piano Sonata K545', opened: 'Yesterday', modified: '3 days ago', starred: false },
  { title: 'Bach Prelude in C Major', opened: '2 days ago', modified: '5 days ago', starred: true },
  { title: 'Chopin Nocturne Op 9 No 2', opened: '3 days ago', modified: '1 week ago', starred: false },
  { title: 'Debussy Clair de Lune', opened: '4 days ago', modified: '2 weeks ago', starred: true },
]

export function Dashboard() {
  const setMusicXML = useScoreStore((s) => s.setMusicXML)
  const [search, setSearch] = useState('')
  const [starredOnly, setStarredOnly] = useState(false)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [sortBy, setSortBy] = useState('lastOpened')

  const filteredScores = MOCK_SCORES.filter((score) => {
    if (starredOnly && !score.starred) return false
    if (search && !score.title.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
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
    <main className="flex-1 bg-nota-50 px-8 py-8">
      <div className="max-w-6xl mx-auto">
        {/* title row */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold text-nota-950">My Scores</h1>
            <p className="text-sm text-gray-500 mt-1">{filteredScores.length} scores</p>
          </div>
          <label className="cursor-pointer inline-flex items-center gap-2 px-6 py-3 bg-nota-900 text-white rounded-full hover:bg-nota-700 transition-colors shadow font-medium">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Upload Score
            <input
              type="file"
              accept=".musicxml,.xml"
              onChange={handleUpload}
              className="hidden"
            />
          </label>
        </div>

        {/* toolbar */}
        <div className="bg-white rounded-xl border border-nota-200 p-4 mb-6">
          <div className="flex items-center gap-4">
            {/* search */}
            <div className="flex-1 relative">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              >
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                placeholder="Search scores..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-nota-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-nota-400 focus:border-transparent text-sm"
              />
            </div>

            {/* sort dropdown */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500 whitespace-nowrap">Sort by:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="border border-nota-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nota-400 bg-white"
              >
                <option value="lastOpened">Last Opened</option>
                <option value="lastModified">Last Modified</option>
                <option value="title">Title</option>
              </select>
            </div>

            {/* starred checkbox */}
            <label className="flex items-center gap-2 cursor-pointer whitespace-nowrap">
              <input
                type="checkbox"
                checked={starredOnly}
                onChange={(e) => setStarredOnly(e.target.checked)}
                className="w-4 h-4 rounded border-nota-300 text-nota-600 focus:ring-nota-400"
              />
              <span className="text-sm text-gray-700">Starred only</span>
            </label>

            {/* view toggle */}
            <div className="flex border border-nota-200 rounded-lg overflow-hidden">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-2 ${viewMode === 'grid' ? 'bg-nota-900 text-white' : 'bg-white text-gray-500 hover:bg-nota-50'}`}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="7" height="7" />
                  <rect x="14" y="3" width="7" height="7" />
                  <rect x="3" y="14" width="7" height="7" />
                  <rect x="14" y="14" width="7" height="7" />
                </svg>
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-2 ${viewMode === 'list' ? 'bg-nota-900 text-white' : 'bg-white text-gray-500 hover:bg-nota-50'}`}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="8" y1="6" x2="21" y2="6" />
                  <line x1="8" y1="12" x2="21" y2="12" />
                  <line x1="8" y1="18" x2="21" y2="18" />
                  <line x1="3" y1="6" x2="3.01" y2="6" />
                  <line x1="3" y1="12" x2="3.01" y2="12" />
                  <line x1="3" y1="18" x2="3.01" y2="18" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        {/* score card grid */}
        <div className={
          viewMode === 'grid'
            ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4'
            : 'flex flex-col gap-3'
        }>
          {filteredScores.map((score) => (
            <ScoreCard
              key={score.title}
              title={score.title}
              opened={score.opened}
              modified={score.modified}
              starred={score.starred}
            />
          ))}
        </div>

        {filteredScores.length === 0 && (
          <p className="text-center text-gray-400 mt-12">No scores found.</p>
        )}
      </div>
    </main>
  )
}
