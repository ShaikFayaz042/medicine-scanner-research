import { useCallback, useState } from 'react'
import SystemGraph from './SystemGraph'
import SfnGraph from './SfnGraph'
import WorkflowHeader from './WorkflowHeader'
import NodeDetailDrawer from './NodeDetailDrawer'
import TimelineScrubber from './TimelineScrubber'
import { usePipelineGraphState } from './usePipelineGraphState'

const VIEWS = [
  { key: 'system', label: 'System',       icon: '◫' },
  { key: 'sfn',    label: 'SFN Execution', icon: 'λ' },
]

export default function WorkflowView({ socket }) {
  const [view, setView] = useState('system')
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const graph = usePipelineGraphState(socket)

  const handleNodeClick = useCallback((_event, node) => {
    setSelectedNodeId((current) => (current === node.id ? null : node.id))
  }, [])

  return (
    <section className="space-y-3">
      <WorkflowHeader
        socketStatus={graph.socketStatus}
        pinnedRunId={graph.pinnedRunId}
        liveRunId={graph.liveRunId}
        onPin={graph.pinRun}
        onUnpin={graph.unpin}
        onReset={graph.reset}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1 rounded-lg bg-[#f3f7fc] p-1 dark:bg-slate-800">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => setView(v.key)}
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
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          {view === 'system' ? 'High-level pipeline topology · live status' : 'AWS Step Functions state machine · pdf-ingestion-pipeline'}
        </p>
      </div>

      <TimelineScrubber
        total={graph.totalEvents}
        scrubIndex={graph.scrubIndex}
        playing={graph.playing}
        onChange={graph.setScrubIndex}
        onPlayToggle={graph.togglePlay}
        oldestAt={graph.oldestAt}
        newestAt={graph.newestAt}
        disabled={!graph.runId}
      />

      {view === 'system' ? (
        <SystemGraph
          nodeStates={graph.nodeStates}
          activeEdges={graph.activeEdges}
          onNodeClick={handleNodeClick}
        />
      ) : (
        <SfnGraph
          nodeStates={graph.nodeStates}
          activeEdges={graph.activeEdges}
          onNodeClick={handleNodeClick}
        />
      )}

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