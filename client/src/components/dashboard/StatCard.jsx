export function StatCard({ label, value, detail, tone = 'info', icon: Icon }) {
  const IconComponent = Icon || (() => null)

  return (
    <div className="stat-card" data-tone={tone}>
      <div className="stat-card__content">
        <span className="eyebrow">{label}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
      <IconComponent size={18} />
    </div>
  )
}

export default StatCard
