import { useEffect, useRef } from 'react'
import RelativeTime from '../RelativeTime'

const TONE_STYLES = {
  idle: 'bg-slate-300 dark:bg-slate-600',
  running: 'bg-sky-500 animate-pulse',
  success: 'bg-emerald-500',
  failed: 'bg-rose-500',
}

/** Render ordered pipeline milestones and keep the active item in view. */
export default function StatusFeedPanel({ feed }) {
  const activeRow = useRef(null)
  const activeKey = feed.find((item) => item.tone === 'running')?.key

  useEffect(() => {
    activeRow.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeKey, feed.length])

  return (
    <aside className="lg:sticky lg:top-4 lg:self-start">
      <div className="max-h-[min(72vh,680px)] min-h-[240px] overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-bold text-slate-800 dark:text-slate-100">Run status</h2>
        {feed.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">Waiting for pipeline to start…</p>
        ) : (
          <ol className="space-y-1.5">
            {feed.map((item) => (
              <li
                key={item.key}
                ref={item.key === activeKey ? activeRow : null}
                className="flex min-h-9 items-center gap-2.5 rounded-md px-2 py-1.5"
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${TONE_STYLES[item.tone] || TONE_STYLES.idle}`} />
                <span className={`min-w-0 flex-1 text-xs ${item.tone === 'idle' ? 'text-slate-400 dark:text-slate-500' : 'text-slate-700 dark:text-slate-200'}`}>
                  {item.label}
                </span>
                {item.at && <RelativeTime value={item.at} className="shrink-0 text-[10px] text-slate-400 dark:text-slate-500" />}
              </li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  )
}