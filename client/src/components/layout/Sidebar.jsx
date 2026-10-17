import { Link } from '@tanstack/react-router'
import { Database, Files, Search, Home, History, CalendarClock, CircleCheck } from 'lucide-react'

const nav = [
  { label: 'Home', path: '/admin', icon: Home },
  { label: 'Runs / History', path: '/admin/runs', icon: History },
  { label: 'Documents', path: '/admin/documents', icon: Files },
  { label: 'Approvals', path: '/admin/approvals', icon: CircleCheck },
  { label: 'Medicine Lookup', path: '/admin/lookup', icon: Search },
  { label: 'Sources', path: '/admin/sources', icon: Database },
  { label: 'Scheduler', path: '/admin/scheduler', icon: CalendarClock },
]

export function Sidebar({ pathname, pending, documents }) {
  return (
    <aside className="scanner-sidebar">
      <Link to="/admin" className="brand">
        <span className="brand-mark">MC</span>
        <span className="brand-copy">
          <strong>MediCheck</strong>
          <small>Regulatory Intelligence</small>
        </span>
      </Link>

      <nav className="main-nav">
        {nav.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`nav-link ${pathname === item.path ? 'nav-active' : ''}`}
            title={item.label}
          >
            <item.icon size={18} />
            <span>{item.label}</span>
            {item.path === '/admin/approvals' && <em>{pending}</em>}
            {item.path === '/admin/documents' && <em>{documents.length}</em>}
          </Link>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <span>MediCheck</span>
        <small>Operations console · v2.0</small>
      </div>
    </aside>
  )
}

export default Sidebar
