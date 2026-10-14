export function ApprovalCard({ title = 'Approval', children }) {
  return (
    <div className="panel approval-card">
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export default ApprovalCard
