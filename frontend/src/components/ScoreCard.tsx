import { useState } from 'react'

interface ScoreCardProps {
  title: string
  opened: string
  modified: string
  starred?: boolean
}

export function ScoreCard({ title, opened, modified, starred = false }: ScoreCardProps) {
  const [isStarred, setIsStarred] = useState(starred)

  return (
    <div className="border border-nota-200 rounded-xl p-5 bg-white hover:shadow-md transition-shadow cursor-pointer">
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 bg-nota-100 rounded-lg flex items-center justify-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-nota-700"
          >
            <path d="M9 18V5l12-2v13" />
            <circle cx="6" cy="18" r="3" />
            <circle cx="18" cy="16" r="3" />
          </svg>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation()
            setIsStarred(!isStarred)
          }}
          className="text-nota-700 hover:text-nota-900 transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill={isStarred ? 'currentColor' : 'none'}
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
        </button>
      </div>
      <h3 className="font-semibold text-nota-950 mb-2">{title}</h3>
      <p className="text-sm text-gray-500">Opened: {opened}</p>
      <p className="text-sm text-gray-500">Modified: {modified}</p>
    </div>
  )
}
