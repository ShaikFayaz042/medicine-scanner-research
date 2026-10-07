import { useEffect, useState } from 'react'
import { pipelineApi } from '../pipelineApi'
import StatusBadge from '../components/StatusBadge'
import RelativeTime from '../components/RelativeTime'

export default function RunSelector({ pinnedRunId, liveRunId, onPin, onUnpin }) {
  const [open, setOpen] = useState(false)
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError('')
    pipelineApi.listRuns({ limit: 30 })
      .then((data) => setRuns(Array.isArray(data) ? data : []))
      .catch((err) => setError(err.message || 'Failed to load runs'))
      .finally(() => setLoading(false))
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const handler = (e) => {
      if (!e.target.closest('[data-run-selector]')) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const activeRunId = pinnedRunId || liveRunId
  const label = activeRunId ? activeRunId : 'Waiting for first event…'
  const isFollowing = !pinnedRunId

  return (
    <div className="relative" data-run-selector>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex max-w-[320px] items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-sky-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isFollowing ? 'bg-emerald-500' : 'bg-sky-500'}`} />
        <span className="truncate font-mono text-[11px]" title={label}>{label}</span>
        <span className="shrink-0 text-[9px] text-slate-400">▾</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-96 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <button
            type="button"
            onClick={() => { onUnpin(); setOpen(false) }}
            className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-xs transition hover:bg-slate-50 dark:hover:bg-slate-800 ${
              isFollowing ? 'bg-emerald-50/70 dark:bg-emerald-950/30' : ''
            }`}
          >
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span className="flex-1 font-semibold text-slate-800 dark:text-slate-100">Follow live</span>
            {liveRunId && (
              <span className="truncate font-mono text-[10px] text-slate-500 dark:text-slate-400">{liveRunId}</span>
            )}
            {isFollowing && <span className="text-[10px] font-bold text-emerald-600">●</span>}
          </button>

          <div className="max-h-[420px] overflow-y-auto border-t border-slate-200 dark:border-slate-800">
            {loading && (
              <div className="space-y-1.5 p-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-8 animate-pulse rounded-md bg-slate-100 dark:bg-slate-800" />
                ))}
              </div>
            )}
            {error && <p className="p-3 text-xs text-rose-600">{error}</p>}
            {!loading && !error && runs.length === 0 && (
              <p className="p-3 text-xs text-slate-500 dark:text-slate-400">No runs yet.</p>
            )}
            {!loading && runs.map((run) => {
              const selected = pinnedRunId === run.run_id
              return (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => { onPin(run.run_id); setOpen(false) }}
                  className={`flex w-full items-center gap-2.5 border-b border-slate-100 px-3 py-2 text-left text-xs transition last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800 ${
                    selected ? 'bg-sky-50 dark:bg-sky-950/40' : ''
                  }`}
                >
                  <StatusBadge value={run.status} />
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-700 dark:text-slate-200">
                    {run.run_id}
                  </span>
                  <RelativeTime value={run.requested_at} className="shrink-0 text-[10px] text-slate-400" />
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}