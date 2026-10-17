import { Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useScanner } from './context';
import { PageHeading, Schedule, Stats } from './shared';
import WorkflowView from '@/components/workflow/WorkflowView';
import { useWorkflowSocket } from '@/hooks/useWorkflowSocket';
import './home-workflow.css';

export function HomePage() {
    const { trigger, isTriggering, requestedRunId } = useScanner();
    const socket = useWorkflowSocket({ enabled: true });

    return <main className="page-content">
        <PageHeading
            eyebrow="MEDICHECK"
            title="Regulatory Intelligence"
            description="Monitor, manage and track regulatory medicine data from multiple government sources."
        />
        <Stats />
        <div className="home-grid">
            <div className="home-main">
                <Schedule compact action={<Button onClick={trigger} disabled={isTriggering}><Play />{isTriggering ? 'Starting…' : 'Trigger Now'}</Button>} />
                <WorkflowView socket={socket} requestedRunId={requestedRunId} />
            </div>
        </div>
    </main>;
}