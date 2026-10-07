import { useEffect, useMemo, useState } from 'react'
import EventRow from '../components/EventRow'
import RelativeTime from '../components/RelativeTime'
import { filterEventsForNode, findNodeMeta } from './stateMapper'
import { getManifestLink, getNodeArtifacts } from './s3Links'

const STATE_LABEL = {
  idle:    { label: 'Idle',    dot: 'bg-slate-400',              tone: 'text-slate-500' },
  running: { label: 'Running', dot: 'bg-sky-500 animate-pulse',  tone: 'text-sky-600' },
  success: { label: 'Success', dot: 'bg-emerald-500',            tone: 'text-emerald-600' },
  failed:  { label: 'Failed',  dot: 'bg-rose-500',               tone: 'text-rose-600' },
  skipped: { label: 'Skipped', dot: 'bg-slate-400',              tone: 'text-slate-500' },
}

function CopyChip({ value, label }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch { /* noop */ }
  }
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy"
      className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
    >
      <span className="truncate">{label || value}</span>
      <span className="shrink-0 text-[9px] opacity-70">{copied ? '✓' : '⧉'}</span>
    </button>
  )
}

function ecsTaskConsoleUrl(taskArn, region = 'ap-south-1') {
  if (!taskArn) return null
  const taskId = taskArn.split('/').pop()
  return `https://${region}.console.aws.amazon.com/ecs/v2/clusters/medicine-scanner-cluster/tasks/${taskId}?region=${region}`
}

export default function NodeDetailDrawer({ nodeId, state = 'idle', events, runId, onClose }) {
  const meta = useMemo(() => findNodeMeta(nodeId), [nodeId])
  const scopedEvents = useMemo(() => filterEventsForNode(nodeId, events), [nodeId, events])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const runEvents = useMemo(
    () => (runId ? scopedEvents.filter((e) => e.run_id === runId) : scopedEvents),
    [scopedEvents, runId]
  )

  const { taskArn, region, lastAt } = useMemo(() => {
    let taskArn = null
    let region = 'ap-south-1'
    let lastAt = null
    for (const e of runEvents) {
      const detail = e.payload?.detail || {}
      if (!taskArn && detail.taskArn) taskArn = detail.taskArn
      if (e.payload?.region) region = e.payload.region
      if (!lastAt && e.timestamp) lastAt = e.timestamp
    }
    return { taskArn, region, lastAt }
  }, [runEvents])

  const artifacts = useMemo(() => getNodeArtifacts(nodeId, runId, region), [nodeId, runId, region])
  const manifest = useMemo(() => getManifestLink(runId, region), [runId, region])

  if (!meta) return null

  const stateInfo = STATE_LABEL[state] || STATE_LABEL.idle
  const hasArtifacts = artifacts.length > 0 || manifest

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="relative z-50 flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4 dark:border-slate-800">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-sky-700 dark:text-sky-400">
              Node detail
            </p>
            <h2 className="mt-1 truncate text-lg font-bold text-slate-900 dark:text-slate-100">
              {meta.data?.label || meta.id}
            </h2>
            {meta.data?.sub && (
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{meta.data.sub}</p>
            )}
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className={`inline-flex items-center gap-1.5 font-semibold ${stateInfo.tone}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${stateInfo.dot}`} />
                {stateInfo.label}
              </span>
              {lastAt && (
                <>
                  <span className="text-slate-300 dark:text-slate-600">·</span>
                  <span className="text-slate-500 dark:text-slate-400">
                    updated <RelativeTime value={lastAt} />
                  </span>
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-600 shadow-sm hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            Close ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {/* Metadata */}
          <div className="mb-4 space-y-3">
            {runId && (
              <div>
                <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Run ID</p>
                <CopyChip value={runId} />
              </div>
            )}
            {taskArn && (
              <div>
                <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">ECS Task ARN</p>
                <div className="flex flex-col gap-1.5">
                  <CopyChip value={taskArn} />
                  <a
                    href={ecsTaskConsoleUrl(taskArn, region)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] font-semibold text-sky-600 hover:underline dark:text-sky-400"
                  >
                    Open in ECS console →
                  </a>
                </div>
              </div>
            )}
          </div>

          {/* Artifacts */}
          {hasArtifacts && (
            <div className="mb-4">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Artifacts
              </h3>
              <div className="space-y-1.5">
                {manifest && (
                  <a
                    href={manifest.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs transition hover:border-sky-300 hover:bg-white dark:border-slate-700 dark:bg-slate-800 dark:hover:border-sky-700"
                  >
                    <span className="truncate font-semibold text-slate-700 dark:text-slate-200">
                      {manifest.label}
                    </span>
                    <span className="shrink-0 text-[10px] font-bold text-sky-600 dark:text-sky-400">S3 →</span>
                  </a>
                )}
                {artifacts.map((a) => (
                  <a
                    key={a.prefix}
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs transition hover:border-sky-300 hover:bg-sky-50/50 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-sky-700 dark:hover:bg-slate-700/60"
                  >
                    <span className="truncate font-semibold text-slate-700 dark:text-slate-200">
                      {a.label}
                    </span>
                    <span className="shrink-0 text-[10px] font-bold text-sky-600 dark:text-sky-400">S3 →</span>
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Events */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Events ({runEvents.length})
              </h3>
            </div>

            {runEvents.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 py-8 text-center text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-400">
                No events scoped to this node.
              </div>
            ) : (
              <div className="space-y-2">
                {runEvents.map((evt) => (
                  <EventRow key={evt.key} event={evt} />
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  )
}