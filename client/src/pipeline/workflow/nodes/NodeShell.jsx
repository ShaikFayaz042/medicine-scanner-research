import { Handle, Position } from '@xyflow/react'
import { NodeIcon } from './Icons'

// Tone → colour tokens (light + dark)
const TONES = {
  amber:   { border: 'border-amber-300 dark:border-amber-700/70',   iconBg: 'bg-amber-100 text-amber-600 dark:bg-amber-950 dark:text-amber-300',       title: 'text-amber-900 dark:text-amber-100' },
  sky:     { border: 'border-sky-300 dark:border-sky-700/70',       iconBg: 'bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-300',               title: 'text-sky-900 dark:text-sky-100' },
  violet:  { border: 'border-violet-300 dark:border-violet-700/70', iconBg: 'bg-violet-100 text-violet-600 dark:bg-violet-950 dark:text-violet-300',   title: 'text-violet-900 dark:text-violet-100' },
  emerald: { border: 'border-emerald-300 dark:border-emerald-700/70', iconBg: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-300', title: 'text-emerald-900 dark:text-emerald-100' },
  teal:    { border: 'border-teal-300 dark:border-teal-700/70',     iconBg: 'bg-teal-100 text-teal-600 dark:bg-teal-950 dark:text-teal-300',           title: 'text-teal-900 dark:text-teal-100' },
  slate:   { border: 'border-slate-300 dark:border-slate-600/70',   iconBg: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300',       title: 'text-slate-800 dark:text-slate-100' },
  rose:    { border: 'border-rose-300 dark:border-rose-700/70',     iconBg: 'bg-rose-100 text-rose-600 dark:bg-rose-950 dark:text-rose-300',           title: 'text-rose-900 dark:text-rose-100' },
}

const STATE_RING = {
  idle:    '',
  running: 'ring-4 ring-sky-200/70 dark:ring-sky-900/60',
  success: 'ring-2 ring-emerald-200/60 dark:ring-emerald-900/50',
  failed:  'ring-4 ring-rose-200/70 dark:ring-rose-900/60',
  skipped: 'opacity-50',
}

const STATUS_DOT = {
  running: 'bg-sky-500 animate-pulse',
  success: 'bg-emerald-500',
  failed:  'bg-rose-500',
}

export function NodeShell({ label, sub, icon, state = 'idle', tone = 'slate', compact = false, accent, children }) {
  const t = TONES[tone] || TONES.slate
  const ring = STATE_RING[state] || ''

  return (
    <div
      className={`group flex cursor-pointer items-center gap-2.5 rounded-xl border-2 bg-white ${t.border} ${ring} ${
        compact ? 'min-w-[150px] px-2.5 py-2' : 'min-w-[180px] px-3 py-2.5'
      } shadow-[0_4px_14px_rgba(27,65,110,0.08)] transition-all duration-300 dark:bg-slate-900`}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-900" />

      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${t.iconBg} transition-colors duration-300`}>
        <NodeIcon name={icon} />
      </span>

      <div className="min-w-0 flex-1">
        <div className={`truncate text-[12px] font-bold leading-tight ${t.title}`}>
          {label}
        </div>
        {sub && (
          <div className="mt-0.5 truncate text-[10px] leading-tight text-slate-500 dark:text-slate-400">
            {sub}
          </div>
        )}
      </div>

      {STATUS_DOT[state] && (
        <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[state]}`} />
      )}

      {accent && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: accent }} />}

      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-900" />
      {children}
    </div>
  )
}