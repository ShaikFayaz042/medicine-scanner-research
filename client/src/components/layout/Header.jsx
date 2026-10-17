import { Link } from '@tanstack/react-router'
import {
  Activity,
  ArrowUpRight,
  Bell,
  CircleAlert,
  CircleCheck,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Sun,
} from 'lucide-react'

import { Button } from '@/components/ui/button'

export function Header({
  search,
  onSearch,
  darkMode,
  onToggleTheme,
  notifications,
  onToggleNotifications,
  read,
  onMarkAllRead,
  profile,
  onToggleProfile,
  onSignOut,
  adminName,
  adminEmail,
  pending,
  onToggleSidebar,
  collapsed,
}) {
  return (
    <header className="global-header">
      <div className="header-search">
        <Button variant="ghost" size="icon" onClick={onToggleSidebar} aria-label="Toggle sidebar" title="Toggle sidebar">
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
        <Search size={16} />
        <input
          aria-label="Global search"
          placeholder="Search documents, medicines, runs..."
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        <span className="search-key">⌘ K</span>
      </div>

      <div className="header-actions">
        <Button
          variant="ghost"
          size="icon"
          title={darkMode ? 'Switch to light theme' : 'Switch to dark theme'}
          aria-label={darkMode ? 'Switch to light theme' : 'Switch to dark theme'}
          aria-pressed={darkMode}
          onClick={onToggleTheme}
        >
          {darkMode ? <Sun /> : <Moon />}
        </Button>

        <div className="notification-anchor">
          <Button variant="ghost" size="icon" title="Notifications" aria-label="Notifications" onClick={onToggleNotifications}>
            <Bell />
            {!read && <span className="unread-count">3</span>}
          </Button>

          {notifications && (
            <div className="notification-menu">
              <div className="section-title">
                <strong>Notifications</strong>
                <Button variant="link" size="sm" onClick={onMarkAllRead}>Mark all read</Button>
              </div>

              {[
                { title: 'Extraction needs attention', sub: '1 document affected', to: '/documents', icon: CircleAlert },
                { title: 'Approval required', sub: `${pending} batches awaiting review`, to: '/approvals', icon: CircleCheck },
                { title: 'Scraper run completed', sub: '18 documents collected', to: '/runs', icon: Activity },
              ].map((item) => (
                <Link key={item.title} to={item.to} onClick={() => onToggleNotifications(false)} className="notification-item">
                  <item.icon size={19} />
                  <div>
                    <strong>{item.title}</strong>
                    <small>{item.sub}</small>
                  </div>
                  <ArrowUpRight size={14} />
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="profile-anchor">
          <Button variant="ghost" className="profile-button" onClick={onToggleProfile} aria-expanded={profile} aria-haspopup="menu">
            <span className="avatar">{adminName.slice(0, 1).toUpperCase()}</span>
            <span>
              <strong>{adminName}</strong>
              <small>Admin</small>
            </span>
          </Button>

          {profile && (
            <div className="profile-menu admin-profile-menu" role="menu">
              <div className="admin-profile-identity">
                <span className="avatar">{adminName.slice(0, 1).toUpperCase()}</span>
                <div>
                  <strong>{adminName}</strong>
                  {adminEmail && <small>{adminEmail}</small>}
                </div>
              </div>
              <div className="admin-profile-access">
                <span>Access</span>
                <strong>Administrator</strong>
              </div>
              <Button variant="ghost" className="admin-profile-logout" onClick={onSignOut} role="menuitem">
                <LogOut size={16} />
                <span>Sign out</span>
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

export default Header
