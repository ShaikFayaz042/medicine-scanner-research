import { useEffect, useState } from 'react'
import Homepage from './homepage'
import MedicineSearch from './medicineSearch'
import PipelineDashboard from './pipeline/PipelineDashboard'

function resolveView() {
  const path = window.location.pathname
  if (path === '/dashboard') return 'dashboard'
  if (path === '/pipeline') return 'pipeline'
  return 'search'
}

function pathFor(view) {
  if (view === 'dashboard') return '/dashboard'
  if (view === 'pipeline') return '/pipeline'
  return '/'
}

function App() {
  const [view, setView] = useState(resolveView)
  const [isDark, setIsDark] = useState(() => window.localStorage.getItem('medicine-scanner-theme') === 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    window.localStorage.setItem('medicine-scanner-theme', isDark ? 'dark' : 'light')
  }, [isDark])

  useEffect(() => {
    const onPop = () => setView(resolveView())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = (nextView) => {
    setView(nextView)
    window.history.pushState({}, '', pathFor(nextView))
  }

  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: '⌂' },
    { key: 'search', label: 'Identify medicine', icon: '⌕' },
    { key: 'pipeline', label: 'Pipeline', icon: '⚙' },
  ]

  return (
    <div className="min-h-screen bg-[#f3f7fc] text-slate-800 dark:bg-slate-950 dark:text-slate-100">
      <nav className="border-b border-blue-950/30 bg-[#132a4b] text-white shadow-[0_2px_10px_rgba(15,38,71,0.16)]">
        <div className="mx-auto flex max-w-[1350px] items-center justify-between px-5 py-2.5">
          <button type="button" onClick={() => navigate('dashboard')} className="flex items-center gap-3 text-left">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-blue-600 text-sm font-bold text-white shadow-sm">MS</span>
            <span>
              <span className="block text-sm font-bold tracking-tight text-white">Medicine Scanner</span>
              <span className="block text-[11px] text-blue-200">Regulatory intelligence</span>
            </span>
          </button>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 text-xs font-semibold">
              {navItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => navigate(item.key)}
                  className={`rounded-lg px-3 py-2 transition ${view === item.key ? 'bg-blue-500/35 text-white shadow-sm' : 'text-blue-100 hover:bg-white/10'}`}
                >
                  {item.icon}&nbsp; {item.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setIsDark((current) => !current)}
              aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
              title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-blue-300/30 bg-blue-950/30 text-lg text-amber-300 shadow-sm transition hover:border-amber-300/70"
            >
              {isDark ? '☀' : '☾'}
            </button>
          </div>
        </div>
      </nav>
      {view === 'search' && <MedicineSearch />}
      {view === 'dashboard' && <Homepage />}
      {view === 'pipeline' && <PipelineDashboard />}
    </div>
  )
}

export default App
