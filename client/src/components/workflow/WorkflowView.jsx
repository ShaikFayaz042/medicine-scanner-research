import { useCallback, useEffect, useMemo, useState } from 'react'
import SystemGraph from './SystemGraph'
import SfnGraph from './SfnGraph'
import WorkflowHeader from './WorkflowHeader'
import NodeDetailDrawer from './NodeDetailDrawer'
import { useWorkflowGraphState } from '../../hooks/useWorkflowGraphState'
import { SYSTEM_NODES } from './layouts'
import { getStageSnapshot } from './stateMapper'
import { useManifest, useNormalized } from './useManifest'
import { useSequentialHighlight } from './useSequentialHighlight'

const SOURCE_NODES = SYSTEM_NODES.filter((node) => node.type === 'source')

const VIEWS = [
  { key: 'system', label: 'System',       icon: '◫' },
  { key: 'sfn',    label: 'SFN Execution', icon: 'λ' },
]

/** Show the live pipeline graph alongside its run-scoped status feed. */
export default function WorkflowView({ socket, requestedRunId, triggeredAt }) {
  const [view, setView] = useState('system')
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [, setFeedClock] = useState(0)
  const graph = useWorkflowGraphState(socket)
  const pinRun = graph.pinRun
  const currentRunId = graph.runId || requestedRunId
  const snapshot = getStageSnapshot(graph.events, currentRunId)
  const scraperStopped = ['success', 'failed'].includes(snapshot.scraperState)
  const sfnSucceeded = snapshot.sfnStatus === 'SUCCEEDED'
  const manifest = useManifest({ runId: currentRunId, enabled: scraperStopped })
  const normalized = useNormalized({ runId: currentRunId, enabled: sfnSucceeded })
  const highlight = useSequentialHighlight({
    sources: SOURCE_NODES,
    manifest: manifest.manifest,
    scraperState: snapshot.scraperState,
  })

  const statusText = useMemo(() => {
    const states = graph.nodeStates || {}

    if (states.scraper === 'failed') return 'Scraper failed'
    if (states.sfn === 'failed') return 'Workflow failed'
    if (states.sfn === 'success') return 'Workflow completed'
    if (states.processor === 'running') return 'Processing'
    if (states.classifier === 'running') return 'Classifying'
    if (states.extractor === 'running') return 'Extracting'
    if (states.sfn === 'running') return 'Orchestrator started'
    if (states.scraper === 'success') return 'Scraper done'
    if (states.scraper === 'running') return 'Scraper running'
    if (currentRunId || requestedRunId) return 'Starting scraper…'

    return 'Waiting for trigger'
  }, [currentRunId, graph.nodeStates, requestedRunId])

  useEffect(() => {
    if (requestedRunId) pinRun(requestedRunId)
  }, [requestedRunId, pinRun])

  useEffect(() => {
    if (snapshot.scraperState !== 'running') return undefined
    const timer = setInterval(() => setFeedClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [snapshot.scraperState])

  const handleNodeClick = useCallback((_event, node) => {
    setSelectedNodeId((current) => (current === node.id ? null : node.id))
  }, [])

  return (
    <section className="space-y-3">
      <WorkflowHeader
        socketStatus={graph.socketStatus}
        statusText={statusText}
        pinnedRunId={graph.pinnedRunId}
        liveRunId={graph.liveRunId}
        onPin={graph.pinRun}
        onUnpin={graph.unpin}
        viewSelector={(
          <div className="flex items-center gap-1 rounded-lg bg-[#f3f7fc] p-1 dark:bg-slate-800">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                type="button"
                onClick={() => setView(v.key)}
                aria-pressed={view === v.key}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                  view === v.key
                    ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
                }`}
              >
                <span>{v.icon}</span>
                {v.label}
              </button>
            ))}
          </div>
        )}
      />

      <div className="min-w-0">
        {view === 'system' ? (
          <SystemGraph
            nodeStates={graph.nodeStates}
            activeEdges={graph.activeEdges}
            onNodeClick={handleNodeClick}
            subStates={highlight.statusById}
          />
        ) : (
          <SfnGraph
            nodeStates={graph.nodeStates}
            activeEdges={graph.activeEdges}
            onNodeClick={handleNodeClick}
          />
        )}
      </div>

      {selectedNodeId && (
        <NodeDetailDrawer
          nodeId={selectedNodeId}
          state={graph.nodeStates[selectedNodeId] || 'idle'}
          events={graph.events}
          runId={graph.runId}
          onClose={() => setSelectedNodeId(null)}
        />
      )}
    </section>
  )
}