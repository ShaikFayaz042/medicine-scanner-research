import {
  Navigate,
  Outlet,
  createBrowserHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
  useNavigate,
  useParams,
} from '@tanstack/react-router'
import { useState } from 'react'
import { ArrowLeft, LockKeyhole } from 'lucide-react'

import { AppLayout } from './components/layout/AppLayout'
import { Button } from './components/ui/button'
import { ScannerProvider } from './context/ScannerContext'
import { getAdminSession, loginAdmin } from './services/adminAuth'
import Approvals from './pages/Approvals'
import Documents from './pages/Documents'
import Home from './pages/Home'
import Landing from './pages/Landing'
import MedicineLookup from './pages/MedicineLookup'
import Runs from './pages/Runs'
import Scheduler from './pages/Scheduler'
import Sources from './pages/Sources'

function AdminLoginPage({ onSignedIn = () => {} }) {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)
    try {
      await loginAdmin(email, password)
      onSignedIn()
      navigate({ to: '/admin' })
    } catch (loginError) {
      setError(loginError.message)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10 text-foreground">
      <div className="w-full max-w-md border border-border bg-card p-6 shadow-sm sm:p-8">
        <a href="/" className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft size={16} /> Back to MediCheck
        </a>

        <div className="mb-7 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center bg-primary text-primary-foreground">
            <LockKeyhole size={18} />
          </span>
          <div>
            <h1 className="text-xl font-semibold">Admin sign in</h1>
            <p className="text-sm text-muted-foreground">MediCheck operations</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="admin-email" className="text-sm font-medium text-foreground">
              Email
            </label>
            <input
              id="admin-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-sm focus:border-ring focus:outline-none"
              placeholder="admin@example.com"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="admin-password" className="text-sm font-medium text-foreground">
              Password
            </label>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-sm focus:border-ring focus:outline-none"
              placeholder="Password"
            />
          </div>

          {error ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </div>
    </main>
  )
}

function AdminLayout() {
  const signedIn = Boolean(getAdminSession())

  if (!signedIn) {
    return <Navigate to="/admin/login" replace />
  }

  return (
    <ScannerProvider>
      <AppLayout>
        <Outlet />
      </AppLayout>
    </ScannerProvider>
  )
}

function DocumentDetailPage() {
  const { id } = useParams({ strict: false })
  return <Documents selectedId={id} />
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

const route = (path, component) =>
  createRoute({ getParentRoute: () => rootRoute, path, component })

const adminLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/admin',
  component: AdminLayout,
})

const adminRoute = (path, component) =>
  createRoute({ getParentRoute: () => adminLayoutRoute, path, component })

const routeTree = rootRoute.addChildren([
  route('/', Landing),
  route('/admin/login', AdminLoginPage),
  adminLayoutRoute.addChildren([
    adminRoute('/', Home),
    adminRoute('/runs', Runs),
    adminRoute('/documents', Documents),
    createRoute({
      getParentRoute: () => adminLayoutRoute,
      path: '/documents/$id',
      component: DocumentDetailPage,
    }),
    adminRoute('/approvals', Approvals),
    adminRoute('/lookup', MedicineLookup),
    adminRoute('/sources', Sources),
    adminRoute('/scheduler', Scheduler),
  ]),
])

const router = createRouter({
  routeTree,
  history: createBrowserHistory(),
})

export default function App() {
  return <RouterProvider router={router} />
}