import { useEffect, useState } from 'react'

function formatRelative(value) {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return value
  const diff = Date.now() - then
  const abs = Math.abs(diff)
  if (abs < 5_000) return 'just now'
  if (abs < 60_000) return `${Math.round(abs / 1000)}s ago`
  if (abs < 3_600_000) return `${Math.round(abs / 60_000)}m ago`
  if (abs < 86_400_000) return `${Math.round(abs / 3_600_000)}h ago`
  return `${Math.round(abs / 86_400_000)}d ago`
}

export default function RelativeTime({ value, className = '' }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 15_000)
    return () => clearInterval(id)
  }, [])
  return (
    <span className={className} title={value || ''}>
      {formatRelative(value)}
    </span>
  )
}
