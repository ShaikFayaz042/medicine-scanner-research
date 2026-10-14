import { Link } from '@tanstack/react-router'
import { Database, Files, Search, Home, History, CalendarClock, CircleCheck } from 'lucide-react'

const nav = [
  { label: 'Home', path: '/', icon: Home },
  { label: 'Runs / History', path: '/runs', icon: History },
  { label: 'Documents', path: '/documents', icon: Files },
  { label: 'Approvals', path: '/approvals', icon: CircleCheck },
  { label: 'Medicine Lookup', path: '/lookup', icon: Search },
  { label: 'Sources', path: '/sources', icon: Database },
  { label: 'Scheduler', path: '/scheduler', icon: CalendarClock },
]

export function Sidebar({ collapsed, pathname, pending, documents, onToggle }) {
  return (
    <aside className="scanner-sidebar">
      <Link to="/" className="brand">
        <span className="brand-mark">MS</span>
        <span className="brand-copy">
          <strong>Medicine Scanner</strong>
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
            {item.path === '/approvals' && <em>{pending}</em>}
            {item.path === '/documents' && <em>{documents.length}</em>}
          </Link>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <span>Medicine Scanner</span>
        <small>Operations console · v2.0</small>
      </div>
    </aside>
  )
}

export default Sidebar
