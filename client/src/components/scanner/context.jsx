import { createContext, useContext, useState } from 'react';
import { initialRuns, initialDocuments } from '@/lib/scanner-data';
const Context = createContext(null);
export function ScannerProvider({ children }) {
    const [runs] = useState(initialRuns);
    const [documents, setDocuments] = useState(initialDocuments);
    const [notice, setNotice] = useState('');
    const [search, setSearch] = useState('');
    const [isTriggering, setIsTriggering] = useState(false);
    const [requestedRunId, setRequestedRunId] = useState(null);
    const [schedule, setSchedule] = useState({ enabled: true, time: '09:00', zone: 'Asia/Kolkata', frequency: 'Daily' });
    const trigger = () => {
        if (isTriggering) return null;
        setIsTriggering(true);
        setNotice('Starting scraper task…');
        void (async () => {
            try {
                const response = await fetch('/api/scheduler/run-now', { method: 'POST' });
                const result = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(result.detail || `Request failed (${response.status})`);
                setRequestedRunId(result.run_id);
                setNotice(`Run ${result.run_id} started. Waiting for live pipeline events.`);
                return result.run_id;
            } catch (error) {
                setNotice(`Could not start scraper: ${error.message}`);
            } finally {
                setIsTriggering(false);
            }
        })();
        return null;
    };
    const decide = (id, approved, reason) => { setDocuments(p => p.map(d => d.id === id ? { ...d, stage: approved ? 'Approved' : 'Review', status: approved ? 'Approved' : 'Rejected' } : d)); setNotice(`${id} · version 1 ${approved ? 'approved' : 'rejected'} in the demo${reason ? ` — ${reason}` : ''}.`); };
    return <Context.Provider value={{ runs, documents, schedule, setSchedule, trigger, isTriggering, requestedRunId, decide, notice, setNotice, search, setSearch }}>{children}</Context.Provider>;
}
export function useScanner() { const value = useContext(Context); if (!value)
    throw new Error('ScannerProvider is required'); return value; }
