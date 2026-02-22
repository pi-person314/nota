import { useScoreStore } from '../store/scoreStore'

export function PageNav() {
  const { currentPage, totalPages, setCurrentPage } = useScoreStore()

  if (totalPages <= 1) return null

  return (
    <div className="flex items-center gap-4 py-3">
      <button
        onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
        disabled={currentPage <= 1}
        className="px-3 py-1 bg-nota-100 text-nota-800 rounded cursor-pointer hover:bg-nota-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        Prev
      </button>
      <span className="text-sm text-nota-700">
        Page {currentPage} / {totalPages}
      </span>
      <button
        onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
        disabled={currentPage >= totalPages}
        className="px-3 py-1 bg-nota-100 text-nota-800 rounded cursor-pointer hover:bg-nota-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        Next
      </button>
    </div>
  )
}
