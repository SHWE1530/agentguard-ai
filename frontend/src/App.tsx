import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { EventsProvider } from './hooks/useEvents'
import AgentMonitor from './pages/AgentMonitor'
import ArchitecturePage from './pages/Architecture'
import Approvals from './pages/Approvals'
import Audit from './pages/Audit'
import Dashboard from './pages/Dashboard'
import EvaluationPage from './pages/Evaluation'
import IncidentDetail from './pages/IncidentDetail'
import Incidents from './pages/Incidents'
import Judge from './pages/Judge'
import Landing from './pages/Landing'
import Login from './pages/Login'
import ReplayPage from './pages/Replay'
import SimulationLab from './pages/SimulationLab'

/** Redirects to /login when auth is on and there is no session. */
function RequireAuth() {
  const { ready, authorised } = useAuth()
  const loc = useLocation()
  if (!ready) return null
  if (!authorised) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  return <Outlet />
}

export default function App() {
  return (
    <AuthProvider>
    <EventsProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth />}>
          <Route path="/app" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="lab" element={<SimulationLab />} />
            <Route path="monitor" element={<AgentMonitor />} />
            <Route path="incidents" element={<Incidents />} />
            <Route path="incidents/:id" element={<IncidentDetail />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="audit" element={<Audit />} />
            <Route path="evaluation" element={<EvaluationPage />} />
            <Route path="architecture" element={<ArchitecturePage />} />
            <Route path="replay" element={<ReplayPage />} />
            <Route path="judge" element={<Judge />} />
          </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </EventsProvider>
    </AuthProvider>
  )
}
