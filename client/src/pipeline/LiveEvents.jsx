import { useMemo, useState } from 'react'
import EventRow from './components/EventRow'

const EVENT_FILTERS = [
  { key: 'all', label: 'All events' },
  { key: 'sfn.state_change', label: 'SFN' },
  { key: 'ecs.task_state_change', label: 'ECS' },
  { key: 'alarm.state_change', label: 'Alarms' },
]

const STATUS_DOT = {
  open: 'bg-emerald-500',
  connecting: 'bg-amber-400 animate-pulse',
  reconnecting: 'bg-amber-400 animate-pulse',
  closed: 'bg-rose-500',
  idle: 'bg-slate-400',
}

export default function LiveEvents({ socket }) {
  const { events, status, paused, togglePause, clear, bufferedCount } = socket
  const [eventFilter, setEventFilter] = useState('all')
  const [runQuery, setRunQuery] = useState('')

  const filtered = useMemo(() => {
    const query = runQuery.trim().toLowerCase()
    return events.filter((event) => {
      if (eventFilter !== 'all' && event.event_type !== eventFilter) return false
      if (query && !(event.run_id || '').toLowerCase().includes(query)) return false
      return true
    })
  }, [events, eventFilter, runQuery])

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_4px_18px_rgba(27,65,110,0.05)] sm:flex-row sm:items-center sm:justify-between dark:border-slate-700 dark:bg-slate-900">
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status] || STATUS_DOT.idle}`} />
            {status === 'open' ? 'Live' : status === 'reconnecting' ? 'Reconnecting…' : status === 'connecting' ? 'Connecting…' : status === 'closed' ? 'Disconnected' : 'Idle'}
          </span>

          <div className="flex items-center gap-1 rounded-lg bg-[#f3f7fc] p-1 dark:bg-slate-800">
            {EVENT_FILTERS.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setEventFilter(filter.key)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  eventFilter === filter.key
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
              value={runQuery}
              onChange={(event) => setRunQuery(event.target.value)}
              placeholder="Filter by run_id…"
              className="w-40 border-0 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400 dark:text-slate-100"
            />
          </label>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            {filtered.length} of {events.length}
          </span>
          <button
            type="button"
            onClick={togglePause}
            className={`rounded-lg border px-3 py-1.5 text-xs font-semibold shadow-sm transition ${
              paused
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-200'
                : 'border-slate-200 bg-white text-slate-700 hover:border-amber-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
            }`}
          >
            {paused ? `▶ Resume${bufferedCount ? ` (${bufferedCount})` : ''}` : '⏸ Pause'}
          </button>
          <button
            type="button"
            onClick={clear}
            disabled={!events.length}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-rose-300 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            Clear
          </button>
        </div>
      </header>

      {filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
          {events.length === 0 ? 'Waiting for pipeline events…' : 'No events match the current filters.'}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((event) => (
            <EventRow key={event.key} event={event} />
          ))}
        </div>
      )}
    </section>
  )
}
