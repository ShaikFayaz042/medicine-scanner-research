import { useState } from 'react'
import StatusBadge from './StatusBadge'
import RelativeTime from './RelativeTime'

export default function ApprovalCard({ run, onApprove, onReject }) {
  const [mode, setMode] = useState('idle')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleApprove = async () => {
    setBusy(true)
    setError('')
    try {
      await onApprove(run)
    } catch (err) {
      setError(err.message || 'Approve failed')
    } finally {
      setBusy(false)
    }
  }

  const handleReject = async () => {
    setBusy(true)
    setError('')
    try {
      await onReject(run, notes.trim() || undefined)
    } catch (err) {
      setError(err.message || 'Reject failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_4px_18px_rgba(27,65,110,0.05)] transition hover:border-sky-300 dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <StatusBadge value={run.status} />
            <span className="font-mono text-xs text-slate-700 dark:text-slate-200">{run.run_id}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span>Requested <RelativeTime value={run.requested_at} /></span>
            {run.manifest_key && (
              <span className="truncate font-mono text-[11px]" title={run.manifest_key}>
                {run.manifest_key.split('/').slice(-3).join('/')}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {mode === 'idle' && (
            <>
              <button
                type="button"
                onClick={() => setMode('rejecting')}
                disabled={busy}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-rose-300 hover:text-rose-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                Reject
              </button>
              <button
                type="button"
                onClick={handleApprove}
                disabled={busy}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-wait disabled:opacity-60"
              >
                {busy ? 'Approving…' : '✓ Approve'}
              </button>
            </>
          )}
        </div>
      </div>

      {mode === 'rejecting' && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/60 p-3 dark:border-rose-900 dark:bg-rose-950/40">
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
            Rejection reason (optional)
          </label>
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            rows={2}
            placeholder="Why is this run being rejected?"
            className="mt-1.5 w-full rounded-md border border-rose-200 bg-white px-2.5 py-2 text-xs text-slate-800 outline-none focus:border-rose-400 focus:ring-2 focus:ring-rose-100 dark:border-rose-900 dark:bg-slate-950 dark:text-slate-100"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => { setMode('idle'); setNotes(''); setError('') }}
              disabled={busy}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleReject}
              disabled={busy}
              className="rounded-md bg-rose-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-60"
            >
              {busy ? 'Rejecting…' : 'Confirm reject'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
        </div>
      )}
    </div>
  )
}
