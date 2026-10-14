export function SchedulerCard({ title = 'Scheduler', children }) {
  return (
    <section className="panel scheduler-card">
      <h3>{title}</h3>
      {children}
    </section>
  )
}

export default SchedulerCard
