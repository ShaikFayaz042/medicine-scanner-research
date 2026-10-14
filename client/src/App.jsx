import {
  Outlet,
  createBrowserHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
  useParams,
} from '@tanstack/react-router'

import { AppLayout } from './components/layout/AppLayout'
import { ScannerProvider } from './context/ScannerContext'
import Approvals from './pages/Approvals'
import Documents from './pages/Documents'
import Home from './pages/Home'
import MedicineLookup from './pages/MedicineLookup'
import Runs from './pages/Runs'
import Scheduler from './pages/Scheduler'
import Sources from './pages/Sources'

const rootRoute = createRootRoute({
  component: () => (
    <ScannerProvider>
      <AppLayout>
        <Outlet />
      </AppLayout>
    </ScannerProvider>
  ),
})

const route = (path, component) =>
  createRoute({ getParentRoute: () => rootRoute, path, component })

const routeTree = rootRoute.addChildren([
  route('/', Home),
  route('/runs', Runs),
  route('/documents', Documents),
  createRoute({
    getParentRoute: () => rootRoute,
    path: '/documents/$id',
    component: () => {
      const { id } = useParams({ strict: false })
      return <Documents selectedId={id} />
    },
  }),
  route('/approvals', Approvals),
  route('/lookup', MedicineLookup),
  route('/sources', Sources),
  route('/scheduler', Scheduler),
])

const router = createRouter({
  routeTree,
  history: createBrowserHistory(),
})

export default function App() {
  return <RouterProvider router={router} />
}