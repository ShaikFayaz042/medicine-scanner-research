import { Handle, Position } from '@xyflow/react'
import { NodeShell } from './NodeShell'

export function ServiceNode({ data }) {
  return <NodeShell {...data} />
}

export function StorageNode({ data }) {
  return <NodeShell {...data} />
}

export function SourceNode({ data }) {
  return <NodeShell {...data} />
}

export function SfnNode({ data }) {
  return <NodeShell {...data} />
}

export function SfnStateNode({ data }) {
  return <NodeShell {...data} compact />
}

export function TerminalNode({ data }) {
  const isStart = data.kind === 'start'
  return (
    <div className="relative flex h-12 w-12 items-center justify-center rounded-full border-2 border-slate-300 bg-white text-[10px] font-bold uppercase tracking-wide text-slate-600 shadow-sm dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200">
      {!isStart && <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-900" />}
      {data.label}
      {isStart && <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-900" />}
    </div>
  )
}

// Non-interactive background panel with a floating label
export function PanelNode({ data }) {
  return (
    <div
      className="pointer-events-none h-full w-full rounded-2xl border-2 border-dashed border-slate-300 bg-slate-100 dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="absolute -top-3 left-5 rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
        {data.label}
      </div>
    </div>
  )
}

export const nodeTypes = {
  service: ServiceNode,
  storage: StorageNode,
  source: SourceNode,
  sfn: SfnNode,
  sfnstate: SfnStateNode,
  terminal: TerminalNode,
  panel: PanelNode,
}