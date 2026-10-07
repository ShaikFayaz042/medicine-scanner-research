import { useMemo } from 'react'
import { ReactFlow, Background, BackgroundVariant, Controls, MarkerType } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { SYSTEM_NODES, SYSTEM_EDGES, SYSTEM_PANELS } from './layouts'
import { nodeTypes } from './nodes'
import { useReactFlow } from '@xyflow/react'

const TONE_COLOR = {
  amber:   '#f59e0b',
  sky:     '#0ea5e9',
  violet:  '#8b5cf6',
  emerald: '#10b981',
  teal:    '#14b8a6',
  rose:    '#f43f5e',
  slate:   '#94a3b8',
}

function buildEdge(edge, active) {
  const toneColor = TONE_COLOR[edge.tone] || TONE_COLOR.slate
  const idleColor = '#cbd5e1'

  if (active) {
    return {
      ...edge,
      type: edge.type || 'smoothstep',
      animated: true,
      style: { stroke: toneColor, strokeWidth: 2.25 },
      markerEnd: { type: MarkerType.ArrowClosed, color: toneColor, width: 18, height: 18 },
    }
  }
  return {
    ...edge,
    type: edge.type || 'smoothstep',
    animated: false,
    style: { stroke: idleColor, strokeWidth: 1.5, strokeDasharray: edge.dashed ? '5 5' : undefined },
    markerEnd: { type: MarkerType.ArrowClosed, color: idleColor, width: 18, height: 18 },
  }
}

function WorkflowControls() {
  const { getZoom, zoomTo } = useReactFlow()

  return (
    <Controls
      showInteractive={false}
      onZoomIn={() => zoomTo(getZoom() * 1.25)}
      onZoomOut={() => zoomTo(getZoom() * 0.8)}
      className="pipeline-flow-controls !rounded-lg !border !border-slate-200 !bg-white !text-slate-700 !shadow-sm dark:!border-slate-700 dark:!bg-slate-800 dark:!text-slate-100"
    />
  )
}
export default function SystemGraph({ nodeStates = {}, activeEdges = [], onNodeClick }) {
  const nodes = useMemo(() => {
    const panels = SYSTEM_PANELS.map((p) => ({
      id: p.id,
      type: 'panel',
      position: { x: p.x, y: p.y },
      data: { label: p.label },
      style: { width: p.width, height: p.height },
      draggable: false,
      selectable: false,
      zIndex: -1,
    }))
    const appNodes = SYSTEM_NODES.map((n) => ({
      ...n,
      data: { ...n.data, state: nodeStates[n.id] || 'idle', tone: n.tone },
      draggable: false,
      selectable: true,
    }))
    return [...panels, ...appNodes]
  }, [nodeStates])

  const edges = useMemo(
    () => SYSTEM_EDGES.map((e) => buildEdge(e, activeEdges.includes(e.id))),
    [activeEdges]
  )

  return (
    <div className="h-[calc(100vh-180px)] min-h-[620px] w-full overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50 shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.25}
        maxZoom={1.6}
        onNodeClick={(e, node) => { if (node.type !== 'panel') onNodeClick?.(e, node) }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={2} color="#94a3b8" />
        <WorkflowControls />
      </ReactFlow>
    </div>
  )
}