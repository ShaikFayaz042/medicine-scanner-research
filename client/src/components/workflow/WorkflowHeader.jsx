import RunSelector from './RunSelector'

export default function WorkflowHeader({
  socketStatus,
  statusText,
  pinnedRunId,
  liveRunId,
  onPin,
  onUnpin,
  viewSelector,
}) {
  const dotColor = socketStatus === 'open' ? 'bg-emerald-500' : socketStatus === 'reconnecting' || socketStatus === 'connecting' ? 'bg-amber-400' : socketStatus === 'closed' ? 'bg-rose-500' : 'bg-slate-400'

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white p-3 shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-800">
          <span className={`h-2 w-2 rounded-full ${dotColor}`} />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">{statusText}</span>
        </div>
        <RunSelector
          pinnedRunId={pinnedRunId}
          liveRunId={liveRunId}
          onPin={onPin}
          onUnpin={onUnpin}
        />
        {viewSelector}
      </div>
    </div>
  )
}