import RunSelector from './RunSelector'

const STATUS_DOT = {
  open: 'bg-emerald-500',
  connecting: 'bg-amber-400 animate-pulse',
  reconnecting: 'bg-amber-400 animate-pulse',
  closed: 'bg-rose-500',
  idle: 'bg-slate-400',
}

export default function WorkflowHeader({
  socketStatus,
  pinnedRunId,
  liveRunId,
  onPin,
  onUnpin,
  onReset,
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white p-3 shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-3">
        <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[socketStatus] || STATUS_DOT.idle}`} />
          {socketStatus === 'open' ? 'Live' : socketStatus === 'reconnecting' ? 'Reconnecting…' : socketStatus === 'connecting' ? 'Connecting…' : socketStatus === 'closed' ? 'Disconnected' : 'Idle'}
        </span>

        <RunSelector
          pinnedRunId={pinnedRunId}
          liveRunId={liveRunId}
          onPin={onPin}
          onUnpin={onUnpin}
        />
      </div>

      <button
        type="button"
        onClick={onReset}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-rose-300 hover:text-rose-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
      >
        ↺ Reset canvas
      </button>
    </div>
  )
}