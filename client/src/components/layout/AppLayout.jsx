import { useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { CircleCheck, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useScanner } from '@/context/ScannerContext'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function AppLayout({ children }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const [collapsed, setCollapsed] = useState(false)
  const [notifications, setNotifications] = useState(false)
  const [read, setRead] = useState(false)
  const [profile, setProfile] = useState(false)
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('medicine-scanner-theme') === 'dark')

  const { documents, search, setSearch, notice, setNotice } = useScanner()
  const pending = documents.filter((document) => document.status === 'In review').length

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    localStorage.setItem('medicine-scanner-theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  return (
    <div className={`scanner-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        collapsed={collapsed}
        pathname={pathname}
        pending={pending}
        documents={documents}
        onToggle={() => setCollapsed((value) => !value)}
      />

      <div className="workspace">
        <Header
          search={search}
          onSearch={setSearch}
          darkMode={darkMode}
          onToggleTheme={() => setDarkMode((value) => !value)}
          notifications={notifications}
          onToggleNotifications={() => setNotifications((value) => !value)}
          read={read}
          onMarkAllRead={() => setRead(true)}
          profile={profile}
          onToggleProfile={() => setProfile((value) => !value)}
          pending={pending}
          onToggleSidebar={() => setCollapsed((value) => !value)}
          collapsed={collapsed}
        />

        {notice && (
          <div role="status" className="notice-bar">
            <CircleCheck size={16} />
            <span>{notice}</span>
            <Button variant="ghost" size="icon" aria-label="Dismiss message" onClick={() => setNotice('')}>
              <X />
            </Button>
          </div>
        )}

        {children}
      </div>
    </div>
  )
}

export default AppLayout
