export function RecentActivity({ items = [] }) {
  return (
    <section className="panel recent-activity">
      <h3>Recent Activity</h3>
      {items.length ? (
        <ul>
          {items.map((item, index) => (
            <li key={`${item.label}-${index}`}>{item.label}</li>
          ))}
        </ul>
      ) : (
        <p>No recent activity.</p>
      )}
    </section>
  )
}

export default RecentActivity
