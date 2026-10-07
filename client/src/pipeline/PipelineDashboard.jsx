import { useState } from 'react'
import { usePipelineSocket } from './usePipelineSocket'
import WorkflowView from './workflow/WorkflowView'
import LiveEvents from './LiveEvents'
import Approvals from './Approvals'
import Runs from './Runs'

const TABS = [
    { key: 'workflow', label: 'Workflow', icon: '◫' },
    { key: 'live', label: 'Live Events', icon: '●' },
    { key: 'approvals', label: 'Approvals', icon: '⏳' },
    { key: 'runs', label: 'Run History', icon: '▤' },
]

export default function PipelineDashboard() {
    const [tab, setTab] = useState('workflow')
    const [approvalNonce, setApprovalNonce] = useState(0)
    const socket = usePipelineSocket({ enabled: true })

    // Static for now — live wiring next wave
    const nodeStates = {}
    const activeEdges = []

    return (
        <main className="min-h-[calc(100vh-66px)] px-4 py-8 text-slate-800 dark:text-slate-100 sm:px-6">
            <div className="mx-auto max-w-[1500px]">
                <header className="mb-5">
                    <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-sky-700">Pipeline control</p>
                    <h1 className="mt-2 text-2xl font-bold tracking-tight text-[#0d2443] dark:text-slate-100">
                        Ingestion pipeline
                    </h1>
                    <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
                        Live workflow canvas, real-time events, approval gate, and run history.
                    </p>
                </header>

                <nav className="mb-5 flex max-w-full gap-1 overflow-x-auto rounded-lg bg-[#f3f7fc] p-1 dark:bg-slate-800">
                    {TABS.map((item) => (
                        <button
                            key={item.key}
                            type="button"
                            onClick={() => setTab(item.key)}
                            className={`flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold transition ${tab === item.key
                                    ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                                    : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
                                }`}
                            aria-pressed={tab === item.key}
                        >
                            <span>{item.icon}</span>
                            {item.label}
                            {item.key === 'live' && socket.status === 'open' && (
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" title="Live" />
                            )}
                        </button>
                    ))}
                </nav>

                {tab === 'workflow' && <WorkflowView socket={socket} />}
                {tab === 'live' && <LiveEvents socket={socket} />}
                {tab === 'approvals' && (
                    <Approvals key={approvalNonce} onApprovalChanged={() => setApprovalNonce((n) => n + 1)} />
                )}
                {tab === 'runs' && <Runs key={approvalNonce} />}
            </div>
        </main>
    )
}