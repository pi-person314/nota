export function Header() {
  return (
    <header className="bg-nota-900 px-6 py-4 flex items-center justify-between shadow">
      <div className="flex items-center gap-2">
        <div className="h-8 w-6 overflow-hidden flex items-center justify-center">
          <img src="/nota.png" alt="Nota" className="h-8 max-w-none" />
        </div>
        <span className="text-white text-lg font-bold">Nota</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-white text-sm">pi person</span>
        <button className="text-nota-300 text-sm flex items-center gap-1 hover:text-nota-200 transition-colors cursor-pointer">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Log Out
        </button>
      </div>
    </header>
  )
}
