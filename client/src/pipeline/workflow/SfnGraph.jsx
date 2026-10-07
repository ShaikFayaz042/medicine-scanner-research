import { useMemo } from 'react'
import { ReactFlow, Background, BackgroundVariant, Controls, MarkerType } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { SFN_NODES, SFN_EDGES } from './layouts'
import { nodeTypes } from './nodes'

const TONE_COLOR = {
  sky:     '#0ea5e9',
  violet:  '#8b5cf6',
  emerald: '#10b981',
  rose:    '#f43f5e',
  slate:   '#94a3b8',
}

function buildEdge(edge, active) {
  const toneColor = TONE_COLOR[edge.tone] || TONE_COLOR.slate
  const idleColor = edge.dashed ? TONE_COLOR.rose : '#cbd5e1'

  if (active) {
    return {
      ...edge,
      type: 'smoothstep',
      animated: true,
      style: { stroke: toneColor, strokeWidth: 2.5, strokeDasharray: edge.dashed ? '6 4' : undefined },
      markerEnd: { type: MarkerType.ArrowClosed, color: toneColor, width: 18, height: 18 },
      label: edge.label,
      labelBgStyle: { fill: 'transparent' },
      labelStyle: { fill: '#64748b', fontSize: 10, fontWeight: 600 },
      labelBgPadding: [4, 2],
    }
  }
  return {
    ...edge,
    type: 'smoothstep',
    animated: false,
    style: { stroke: idleColor, strokeWidth: edge.dashed ? 1.8 : 1.5, strokeDasharray: edge.dashed ? '6 4' : undefined },
    markerEnd: { type: MarkerType.ArrowClosed, color: idleColor, width: 18, height: 18 },
    label: edge.label,
    labelBgStyle: { fill: 'transparent' },
    labelStyle: { fill: '#94a3b8', fontSize: 10, fontWeight: 600 },
    labelBgPadding: [4, 2],
  }
}

export default function SfnGraph({ nodeStates = {}, activeEdges = [], onNodeClick }) {
  const nodes = useMemo(
    () => SFN_NODES.map((n) => ({
      ...n,
      data: { ...n.data, state: nodeStates[n.id] || 'idle', tone: n.tone },
      draggable: false,
    })),
    [nodeStates]
  )

  const edges = useMemo(
    () => SFN_EDGES.map((e) => buildEdge(e, activeEdges.includes(e.id))),
    [activeEdges]
  )

  return (
    <div className="h-[calc(100vh-300px)] min-h-[520px] w-full overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
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
        onNodeClick={(e, node) => onNodeClick?.(e, node)}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#cbd5e1" />
        <Controls
          showInteractive={false}
          className="pipeline-flow-controls !rounded-lg !border !border-slate-200 !bg-white !text-slate-700 !shadow-sm dark:!border-slate-700 dark:!bg-slate-800 dark:!text-slate-100"
        />
      </ReactFlow>
    </div>
  )
}