import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { EventsProvider } from './hooks/useEvents'
import AgentMonitor from './pages/AgentMonitor'
import Approvals from './pages/Approvals'
import Audit from './pages/Audit'
import Dashboard from './pages/Dashboard'
import IncidentDetail from './pages/IncidentDetail'
import Incidents from './pages/Incidents'
import Landing from './pages/Landing'
import ModelEvaluation from './pages/ModelEvaluation'
import SimulationLab from './pages/SimulationLab'

export default function App() {
  return (
    <EventsProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="lab" element={<SimulationLab />} />
            <Route path="monitor" element={<AgentMonitor />} />
            <Route path="incidents" element={<Incidents />} />
            <Route path="incidents/:id" element={<IncidentDetail />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="audit" element={<Audit />} />
            <Route path="model" element={<ModelEvaluation />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </EventsProvider>
  )
}
