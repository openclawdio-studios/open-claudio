import { NavLink } from 'react-router-dom'
import { MessageSquare, Activity, BarChart2, BookOpen, Zap, Wrench, Users } from 'lucide-react'
import { clsx } from 'clsx'

const NAV = [
  { to: '/playground', icon: MessageSquare, label: 'Playground' },
  { to: '/traces', icon: Activity, label: 'Traces' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics' },
  { to: '/knowledge', icon: BookOpen, label: 'Knowledge' },
  { to: '/events', icon: Zap, label: 'Events' },
  { to: '/tools', icon: Wrench, label: 'Tools' },
  { to: '/users', icon: Users, label: 'Users' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="h-14 flex items-center px-5 border-b border-gray-800">
          <span className="text-brand-500 font-bold text-lg tracking-tight">Open-Claudio</span>
        </div>
        <nav className="flex-1 py-4 space-y-1 px-3">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-3 border-t border-gray-800 text-xs text-gray-600">v1.0.0</div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto bg-gray-950">
        {children}
      </main>
    </div>
  )
}
