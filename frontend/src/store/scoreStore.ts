import { create } from 'zustand'

interface ScoreState {
  musicxml: string | null
  fileName: string | null
  currentPage: number
  totalPages: number
  setMusicXML: (xml: string, fileName: string) => void
  setCurrentPage: (page: number) => void
  setTotalPages: (total: number) => void
  clear: () => void
}

export const useScoreStore = create<ScoreState>((set) => ({
  musicxml: null,
  fileName: null,
  currentPage: 1,
  totalPages: 1,
  setMusicXML: (xml, fileName) => set({ musicxml: xml, fileName, currentPage: 1 }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setTotalPages: (total) => set({ totalPages: total }),
  clear: () => set({ musicxml: null, fileName: null, currentPage: 1, totalPages: 1 }),
}))
