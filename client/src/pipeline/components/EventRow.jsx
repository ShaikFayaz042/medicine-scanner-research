import { useState } from 'react'
import StatusBadge from './StatusBadge'
import RelativeTime from './RelativeTime'

const EVENT_LABELS = {
  'sfn.state_change': 'SFN',
  'ecs.task_state_change': 'ECS',
  'alarm.state_change': 'Alarm',
  unknown: 'Event',
}

export default function EventRow({ event }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const copyRunId = async (event_) => {
    event_.stopPropagation()
    if (!event.run_id) return
    try {
      await navigator.clipboard.writeText(event.run_id)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch { /* noop */ }
  }

  return (
    <div
      className={`group rounded-xl border bg-white transition dark:bg-slate-900 ${
        event.isHistory
          ? 'border-slate-200/60 dark:border-slate-800'
          : 'border-slate-200/80 hover:border-sky-300 dark:border-slate-700 dark:hover:border-sky-700'
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 p-3.5 text-left"
        aria-expanded={open}
      >
        <div className="flex shrink-0 flex-col items-start gap-1.5">
          <StatusBadge value={event.event_type} label={EVENT_LABELS[event.event_type] || 'Event'} />
          {event.status && <StatusBadge value={event.status} />}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            {event.run_id ? (
              <button
                type="button"
                onClick={copyRunId}
                className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                title="Copy run_id"
              >
                {event.run_id}
                <span className="text-[9px] opacity-70">{copied ? '✓' : '⧉'}</span>
              </button>
            ) : (
              <span className="text-slate-400">no run_id</span>
            )}
            <span className="text-slate-300 dark:text-slate-600">·</span>
            <span className="font-medium text-slate-600 dark:text-slate-300">{event.source}</span>
            <span className="text-slate-300 dark:text-slate-600">·</span>
            <RelativeTime value={event.timestamp} />
            {event.isHistory && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                history
              </span>
            )}
          </div>
          <div className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
            {event.payload?.detail?.status && <span className="mr-2">status: {String(event.payload.detail.status)}</span>}
            {event.payload?.detail?.stopCode && <span className="mr-2">stop: {String(event.payload.detail.stopCode)}</span>}
            {event.payload?.detail?.containers?.[0]?.exitCode != null && (
              <span className="mr-2">exit: {String(event.payload.detail.containers[0].exitCode)}</span>
            )}
          </div>
        </div>

        <span className="shrink-0 self-center text-slate-400 transition group-hover:text-slate-600 dark:group-hover:text-slate-200">
          {open ? '▾' : '▸'}
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-200/80 bg-slate-50/60 p-3 dark:border-slate-800 dark:bg-slate-950/40">
          <pre className="max-h-72 overflow-auto rounded-lg bg-white p-3 font-mono text-[11px] leading-5 text-slate-700 shadow-inner dark:bg-slate-950 dark:text-slate-300">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
