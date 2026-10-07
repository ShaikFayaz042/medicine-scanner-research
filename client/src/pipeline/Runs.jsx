import { useCallback, useEffect, useMemo, useState } from 'react'
import { pipelineApi } from './pipelineApi'
import StatusBadge from './components/StatusBadge'
import RelativeTime from './components/RelativeTime'
import EventRow from './components/EventRow'

const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
]

export default function Runs() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [drawerEvents, setDrawerEvents] = useState([])
  const [drawerLoading, setDrawerLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await pipelineApi.listRuns({ limit: 200 })
      setRuns(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message || 'Failed to load runs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return runs.filter((run) => {
      if (statusFilter !== 'all' && run.status !== statusFilter) return false
      if (q && !`${run.run_id} ${run.decided_by || ''}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [runs, statusFilter, query])

  useEffect(() => {
    if (!selected) { setDrawerEvents([]); return undefined }
    let cancelled = false
    setDrawerLoading(true)
    pipelineApi.listEvents({ runId: selected.run_id, limit: 200 })
      .then((events) => {
        if (cancelled) return
        const normalized = (Array.isArray(events) ? events : []).map((raw) => ({
          key: String(raw.id ?? `${raw.event_type}-${raw.received_at}`),
          kind: 'history',
          isHistory: true,
          event_type: raw.event_type || 'unknown',
          source: raw.source || 'unknown',
          run_id: raw.run_id || null,
          status: raw.payload?.detail?.status || null,
          timestamp: raw.event_time || raw.received_at,
          payload: raw.payload || {},
        }))
        setDrawerEvents(normalized)
      })
      .catch(() => { if (!cancelled) setDrawerEvents([]) })
      .finally(() => { if (!cancelled) setDrawerLoading(false) })
    return () => { cancelled = true }
  }, [selected])

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_4px_18px_rgba(27,65,110,0.05)] sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:bg-slate-900">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg bg-[#f3f7fc] p-1 dark:bg-slate-800">
            {STATUS_FILTERS.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setStatusFilter(filter.key)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  statusFilter === filter.key
                    ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-400 shadow-sm dark:border-slate-700 dark:bg-slate-800">
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search run_id or admin…"
              className="w-44 border-0 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400 dark:text-slate-100"
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500 dark:text-slate-400">{filtered.length} runs</span>
          <button type="button" onClick={load} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:border-sky-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">↻ Refresh</button>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl border border-slate-200/80 bg-white dark:border-slate-700 dark:bg-slate-900" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
          No runs match the current filters.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                <tr>
                  <th className="px-3 py-3 text-xs font-medium">Run ID</th>
                  <th className="px-3 py-3 text-xs font-medium">Status</th>
                  <th className="px-3 py-3 text-xs font-medium">Requested</th>
                  <th className="px-3 py-3 text-xs font-medium">Decided</th>
                  <th className="px-3 py-3 text-xs font-medium">By</th>
                  <th className="px-3 py-3 text-xs font-medium">Ingester</th>
                  <th className="px-3 py-3 text-xs font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => (
                  <tr
                    key={run.run_id}
                    className="cursor-pointer border-t border-slate-200/80 transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60"
                    onClick={() => setSelected(run)}
                  >
                    <td className="px-3 py-3 font-mono text-xs text-slate-700 dark:text-slate-200">{run.run_id}</td>
                    <td className="px-3 py-3"><StatusBadge value={run.status} /></td>
                    <td className="px-3 py-3 text-xs text-slate-500 dark:text-slate-400"><RelativeTime value={run.requested_at} /></td>
                    <td className="px-3 py-3 text-xs text-slate-500 dark:text-slate-400"><RelativeTime value={run.decided_at} /></td>
                    <td className="px-3 py-3 text-xs text-slate-600 dark:text-slate-300">{run.decided_by || '—'}</td>
                    <td className="px-3 py-3 text-xs text-slate-500 dark:text-slate-400">
                      {run.ingester_task_arn ? (
                        <span className="font-mono text-[11px]" title={run.ingester_task_arn}>
                          {run.ingester_task_arn.split('/').slice(-2).join('/')}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="px-3 py-3 text-right text-xs font-semibold text-sky-600">View →</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-40 flex justify-end">
          <div
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setSelected(null)}
            aria-hidden="true"
          />
          <aside className="relative z-50 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4 dark:border-slate-800">
              <div className="min-w-0">
                <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-sky-700">Run detail</p>
                <h2 className="mt-1 truncate font-mono text-sm text-slate-900 dark:text-slate-100">{selected.run_id}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <StatusBadge value={selected.status} />
                  <span>Requested <RelativeTime value={selected.requested_at} /></span>
                  {selected.decided_at && <span>· Decided <RelativeTime value={selected.decided_at} /></span>}
                  {selected.decided_by && <span>· by {selected.decided_by}</span>}
                </div>
                {selected.manifest_key && (
                  <p className="mt-2 truncate font-mono text-[11px] text-slate-500 dark:text-slate-400" title={selected.manifest_key}>
                    {selected.manifest_key}
                  </p>
                )}
                {selected.notes && (
                  <p className="mt-2 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                    Notes: {selected.notes}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-600 shadow-sm hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                Close ✕
              </button>
            </header>

            <div className="flex-1 overflow-y-auto p-4">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Events ({drawerEvents.length})
              </h3>
              {drawerLoading ? (
                <div className="space-y-2">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="h-16 animate-pulse rounded-lg border border-slate-200/80 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40" />
                  ))}
                </div>
              ) : drawerEvents.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">No events recorded for this run.</p>
              ) : (
                <div className="space-y-2">
                  {drawerEvents.map((event) => <EventRow key={event.key} event={event} />)}
                </div>
              )}
            </div>
          </aside>
        </div>
      )}
    </section>
  )
}
