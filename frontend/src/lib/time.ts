const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR
const WEEK = 7 * DAY

export function relativeTime(ts: number): string {
  const delta = Date.now() - ts
  if (delta < MIN) return 'just now'
  if (delta < HOUR) {
    const m = Math.round(delta / MIN)
    return `${m} min ago`
  }
  if (delta < DAY) {
    const h = Math.round(delta / HOUR)
    return h === 1 ? '1 hr ago' : `${h} hrs ago`
  }
  const days = Math.floor(delta / DAY)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(delta / WEEK)
  if (weeks < 5) return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
  const months = Math.floor(days / 30)
  return months === 1 ? '1 month ago' : `${months} months ago`
}

export function timeOfDayGreeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

const WORDS = [
  'Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six',
  'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
]

export function countWord(n: number): string {
  return n >= 0 && n < WORDS.length ? WORDS[n] : String(n)
}
