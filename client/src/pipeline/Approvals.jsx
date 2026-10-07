import { useCallback, useEffect, useMemo, useState } from 'react'
import { pipelineApi } from './pipelineApi'
import ApprovalCard from './components/ApprovalCard'
import StatusBadge from './components/StatusBadge'
import RelativeTime from './components/RelativeTime'

export default function Approvals({ onApprovalChanged }) {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [flash, setFlash] = useState('')

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

  const pending = useMemo(() => runs.filter((r) => r.status === 'pending'), [runs])
  const recent = useMemo(
    () => runs.filter((r) => r.status !== 'pending').slice(0, 10),
    [runs]
  )

  const handleApprove = async (run) => {
    await pipelineApi.approveRun(run.run_id, { by: 'admin' })
    setFlash(`Run ${run.run_id} approved. Ingester task launched.`)
    await load()
    onApprovalChanged?.()
  }

  const handleReject = async (run, notes) => {
    await pipelineApi.rejectRun(run.run_id, { by: 'admin', notes })
    setFlash(`Run ${run.run_id} rejected.`)
    await load()
    onApprovalChanged?.()
  }

  useEffect(() => {
    if (!flash) return undefined
    const id = setTimeout(() => setFlash(''), 4000)
    return () => clearTimeout(id)
  }, [flash])

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-slate-200/80 bg-white dark:border-slate-700 dark:bg-slate-900" />
        ))}
      </div>
    )
  }

  return (
    <section className="space-y-6">
      {flash && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
          {flash}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
          <button type="button" onClick={load} className="ml-2 underline">Retry</button>
        </div>
      )}

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold text-[#17375e] dark:text-slate-100">
            Pending approvals
            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-950/60 dark:text-amber-200">
              {pending.length}
            </span>
          </h2>
          <button type="button" onClick={load} className="text-xs font-semibold text-sky-600 hover:text-sky-800">↻ Refresh</button>
        </div>

        {pending.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
            🎉 No pending approvals.
          </div>
        ) : (
          <div className="space-y-2">
            {pending.map((run) => (
              <ApprovalCard key={run.run_id} run={run} onApprove={handleApprove} onReject={handleReject} />
            ))}
          </div>
        )}
      </div>

      {recent.length > 0 && (
        <div>
          <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Recent decisions
          </h3>
          <div className="overflow-hidden rounded-xl border border-slate-200/80 bg-white dark:border-slate-700 dark:bg-slate-900">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                <tr>
                  <th className="px-3 py-2 text-xs font-medium">Run</th>
                  <th className="px-3 py-2 text-xs font-medium">Status</th>
                  <th className="px-3 py-2 text-xs font-medium">Decided</th>
                  <th className="px-3 py-2 text-xs font-medium">By</th>
                  <th className="px-3 py-2 text-xs font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((run) => (
                  <tr key={run.run_id} className="border-t border-slate-200/80 dark:border-slate-800">
                    <td className="px-3 py-2 font-mono text-xs text-slate-700 dark:text-slate-200">{run.run_id}</td>
                    <td className="px-3 py-2"><StatusBadge value={run.status} /></td>
                    <td className="px-3 py-2 text-xs text-slate-500 dark:text-slate-400"><RelativeTime value={run.decided_at} /></td>
                    <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">{run.decided_by || '—'}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-xs text-slate-500 dark:text-slate-400" title={run.notes || ''}>{run.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
