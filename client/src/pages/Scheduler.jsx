import { PageHeading, Schedule } from '../components/scanner/shared'

export default function Scheduler() {
  return (
    <main className="page-content">
      <PageHeading
        eyebrow="OPERATIONS / SCHEDULER"
        title="Scheduler / Automation"
        description="Review and manage the automated ingestion schedule and execution cadence."
      />
      <Schedule />
    </main>
  )
}