const TONES = {
  'sfn.state_change': 'bg-indigo-50 text-indigo-700 border-indigo-100 dark:bg-indigo-950/60 dark:text-indigo-200 dark:border-indigo-900',
  'ecs.task_state_change': 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/60 dark:text-amber-200 dark:border-amber-900',
  'alarm.state_change': 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-900',

  SUCCEEDED: 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-900',
  RUNNING: 'bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-950/60 dark:text-sky-200 dark:border-sky-900',
  FAILED: 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-900',
  STOPPED: 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700',
  TIMED_OUT: 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-900',
  ABORTED: 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/60 dark:text-amber-200 dark:border-amber-900',
  OK: 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-900',
  ALARM: 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-900',

  pending: 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-950/60 dark:text-amber-200 dark:border-amber-900',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-900',
  rejected: 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-900',
  ingested: 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-900',

  default: 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700',
}

export default function StatusBadge({ label, value, className = '' }) {
  const tone = TONES[value] || TONES.default
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${tone} ${className}`}
    >
      {label ?? value ?? 'unknown'}
    </span>
  )
}
