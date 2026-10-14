export const initialRuns = [
    { id: 'RUN-1042', trigger: 'Scheduled', source: 'CDSCO FDC', started: 'Today, 09:00 AM', duration: '4m 32s', scraper: 'Success', processing: 'Success', ingestion: 'Success', status: 'Completed', documents: 18 },
    { id: 'RUN-1041', trigger: 'Manual', source: 'CDSCO Alerts', started: 'Today, 08:45 AM', duration: '12m 17s', scraper: 'Success', processing: 'Running', ingestion: 'Pending', status: 'In progress', documents: 12 },
    { id: 'RUN-1040', trigger: 'Scheduled', source: 'Banned Drugs', started: 'Yesterday, 09:00 AM', duration: '8m 03s', scraper: 'Success', processing: 'Failed', ingestion: 'Skipped', status: 'Failed', documents: 8 },
    { id: 'RUN-1039', trigger: 'Manual', source: 'IPC / PvPI', started: '08 Oct, 07:30 PM', duration: '6m 45s', scraper: 'Success', processing: 'Success', ingestion: 'Success', status: 'Completed', documents: 14 },
    { id: 'RUN-1038', trigger: 'Scheduled', source: 'NSQ / Spurious', started: '08 Oct, 06:15 AM', duration: '9m 20s', scraper: 'Success', processing: 'Success', ingestion: 'Pending', status: 'In progress', documents: 10 },
    { id: 'RUN-1037', trigger: 'Scheduled', source: 'CDSCO Alerts', started: '07 Oct, 09:00 AM', duration: '5m 12s', scraper: 'Success', processing: 'Success', ingestion: 'Success', status: 'Completed', documents: 9 },
];
export const initialDocuments = [
    { id: 'DOC-2026-8842', title: 'CDSCO Regulatory Notice - 2026', source: 'CDSCO FDC', type: 'Regulatory Notice', published: '26 Sep 2026', stage: 'Ingested', status: 'Completed', records: 842, run: 'RUN-1042' },
    { id: 'DOC-2026-7731', title: 'List of Banned Drugs - May 2026', source: 'CDSCO Alerts', type: 'Ban List', published: '21 Jul 2026', stage: 'Classification', status: 'Processing', records: 126, run: 'RUN-1041' },
    { id: 'DOC-2026-6610', title: 'Circular on IPC / PvPI', source: 'IPC / PvPI', type: 'Circular', published: '15 Oct 2026', stage: 'Extraction', status: 'Processing', records: 538, run: 'RUN-1040' },
    { id: 'DOC-2026-5520', title: 'Updated Schedule H - 2026', source: 'CDSCO FDC', type: 'Schedule', published: '08 Oct 2026', stage: 'Awaiting approval', status: 'In review', records: 1024, run: 'RUN-1038' },
    { id: 'DOC-2026-4983', title: 'False Drug Alert - Batch 1034', source: 'CDSCO Alerts', type: 'Alert', published: '06 Oct 2026', stage: 'Awaiting approval', status: 'In review', records: 412, run: 'RUN-1037' },
    { id: 'DOC-2026-4412', title: 'ADR Report - 2026', source: 'IPC / PvPI', type: 'Adverse Event', published: '04 Oct 2026', stage: 'Awaiting approval', status: 'In review', records: 276, run: 'RUN-1039' },
    { id: 'DOC-2026-3921', title: 'Import Alert - 2026', source: 'CDSCO FDC', type: 'Alert', published: '01 Oct 2026', stage: 'Awaiting approval', status: 'In review', records: 198, run: 'RUN-1035' },
    { id: 'DOC-2026-3310', title: 'Quality Standards Update', source: 'CDSCO FDC', type: 'Guideline', published: '28 Sep 2026', stage: 'Awaiting approval', status: 'In review', records: 641, run: 'RUN-1034' },
    { id: 'DOC-2026-2875', title: 'Drug Recall Notice - 2026', source: 'CDSCO Alerts', type: 'Recall', published: '25 Sep 2026', stage: 'Extraction', status: 'Failed', records: 329, run: 'RUN-1033' },
    { id: 'DOC-2026-2456', title: 'New Medicine Approval', source: 'CDSCO FDC', type: 'Approval', published: '20 Sep 2026', stage: 'Awaiting approval', status: 'In review', records: 152, run: 'RUN-1032' },
];
export const medicines = [['Paracetamol', '500 mg'], ['Ibuprofen', '400 mg'], ['Amoxicillin', '250 mg'], ['Cetirizine', '10 mg'], ['Metformin', '500 mg'], ['Atorvastatin', '10 mg'], ['Ranitidine', '150 mg'], ['Azithromycin', '250 mg']];
export const steps = ['Scheduler', 'Scraper', 'Extraction', 'Classification', 'Normalization', 'Ingestion'];
export function downloadText(name, content, type = 'text/plain') { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url); }
