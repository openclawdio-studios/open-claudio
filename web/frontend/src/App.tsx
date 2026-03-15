import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Playground from './pages/Playground'
import Traces from './pages/Traces'
import TraceDetail from './pages/TraceDetail'
import Analytics from './pages/Analytics'
import KnowledgeBase from './pages/KnowledgeBase'
import Events from './pages/Events'
import Tools from './pages/Tools'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/playground" replace />} />
        <Route path="/playground" element={<Playground />} />
        <Route path="/traces" element={<Traces />} />
        <Route path="/traces/:id" element={<TraceDetail />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/knowledge" element={<KnowledgeBase />} />
        <Route path="/events" element={<Events />} />
        <Route path="/tools" element={<Tools />} />
      </Routes>
    </Layout>
  )
}
