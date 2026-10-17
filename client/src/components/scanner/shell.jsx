import { Link, useRouterState } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { Home, Files, CircleCheck, Search, Database, Workflow, Settings, Bell, ChevronDown, PanelLeftClose, PanelLeftOpen, Activity, X, ArrowUpRight, History, CircleAlert, Moon, Sun, CalendarClock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useScanner } from './context';
const nav = [{ label: 'Home', path: '/', icon: Home }, { label: 'Runs / History', path: '/runs', icon: History }, { label: 'Documents', path: '/documents', icon: Files }, { label: 'Approvals', path: '/approvals', icon: CircleCheck }, { label: 'Medicine Lookup', path: '/lookup', icon: Search }, { label: 'Sources', path: '/sources', icon: Database }, { label: 'Scheduler', path: '/scheduler', icon: CalendarClock }];
export function ScannerShell({ children }) {
    const pathname = useRouterState({ select: s => s.location.pathname });
    const [collapsed, setCollapsed] = useState(false);
    const [notifications, setNotifications] = useState(false);
    const [read, setRead] = useState(false);
    const [profile, setProfile] = useState(false);
    const [darkMode, setDarkMode] = useState(() => localStorage.getItem('medicine-scanner-theme') === 'dark');
    const { documents, search, setSearch, notice, setNotice } = useScanner();
    const pending = documents.filter(d => d.status === 'In review').length;
    useEffect(() => {
        document.documentElement.classList.toggle('dark', darkMode);
        localStorage.setItem('medicine-scanner-theme', darkMode ? 'dark' : 'light');
    }, [darkMode]);
    return <div className={`scanner-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
 <aside className="scanner-sidebar"><Link to="/" className="brand"><span className="brand-mark">MC</span><span className="brand-copy"><strong>MediCheck</strong><small>Regulatory Intelligence</small></span></Link>
 <nav className="main-nav">{nav.map(n => <Link key={n.path} to={n.path} className={`nav-link ${pathname === n.path ? 'nav-active' : ''}`} title={n.label}><n.icon size={18}/><span>{n.label}</span>{n.path === '/approvals' && <em>{pending}</em>}{n.path === '/documents' && <em>{documents.length}</em>}</Link>)}</nav>
 <div className="nav-section">OPERATIONS</div><Link to="/settings" className={`nav-link ${pathname === '/settings' ? 'nav-active' : ''}`} title="Settings"><Settings size={18}/><span>Settings</span></Link>
 <div className="sidebar-bottom"><span>MediCheck</span><small>Operations console · v2.0</small></div></aside>
 <div className="workspace"><header className="global-header"><div className="header-search"><Button variant="ghost" size="icon" onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar" title="Toggle sidebar">{collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}</Button><Search size={16}/><input aria-label="Global search" placeholder="Search documents, medicines, runs..." value={search} onChange={e => setSearch(e.target.value)}/><span className="search-key">⌘ K</span></div> <div className="header-actions"><Button variant="ghost" size="icon" title={darkMode ? 'Switch to light theme' : 'Switch to dark theme'} aria-label={darkMode ? 'Switch to light theme' : 'Switch to dark theme'} aria-pressed={darkMode} onClick={() => setDarkMode(!darkMode)}>{darkMode ? <Sun /> : <Moon />}</Button><div className="notification-anchor"><Button variant="ghost" size="icon" title="Notifications" aria-label="Notifications" onClick={() => setNotifications(!notifications)}><Bell />{!read && <span className="unread-count">3</span>}</Button>{notifications && <div className="notification-menu"><div className="section-title"><strong>Notifications</strong><Button variant="link" size="sm" onClick={() => setRead(true)}>Mark all read</Button></div>{[{ title: 'Extraction needs attention', sub: '1 document affected', to: '/documents', icon: CircleAlert }, { title: 'Approval required', sub: `${pending} batches awaiting review`, to: '/approvals', icon: CircleCheck }, { title: 'Scraper run completed', sub: '18 documents collected', to: '/runs', icon: Activity }].map(n => <Link key={n.title} to={n.to} onClick={() => setNotifications(false)} className="notification-item"><n.icon size={19}/><div><strong>{n.title}</strong><small>{n.sub}</small></div><ArrowUpRight size={14}/></Link>)}</div>}</div><div className="profile-anchor"><Button variant="ghost" className="profile-button" onClick={() => setProfile(!profile)}><span className="avatar">F</span><span><strong>Shaik Fayaz</strong><small>Admin</small></span><ChevronDown size={14}/></Button>{profile && <div className="profile-menu"><strong>Shaik Fayaz</strong><small>Administrator</small><Link to="/settings" onClick={() => setProfile(false)}>Workspace settings <ArrowUpRight size={14}/></Link></div>}</div></div></header>
 {notice && <div role="status" className="notice-bar"><CircleCheck size={16}/><span>{notice}</span><Button variant="ghost" size="icon" aria-label="Dismiss message" onClick={() => setNotice('')}><X /></Button></div>}{children}</div></div>;
}
