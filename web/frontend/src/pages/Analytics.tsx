import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid
} from 'recharts'
import { api } from '../api'
import { ShieldCheck, User } from 'lucide-react'

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-gray-900 rounded-xl p-5">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="text-2xl font-semibold text-gray-100">{value.toLocaleString()}</div>
    </div>
  )
}

export default function Analytics() {
  const { data: summary = {} } = useQuery({ queryKey: ['analytics-summary'], queryFn: api.analytics.summary, refetchInterval: 30_000 })
  const { data: dailyTokens = [] } = useQuery({ queryKey: ['daily-tokens'], queryFn: api.analytics.dailyTokens })
  const { data: toolRates = [] } = useQuery({ queryKey: ['tool-rates'], queryFn: api.analytics.toolSuccessRates })

  const viewer = (summary as Record<string, unknown>)._viewer as string | null
  const isAdmin = (summary as Record<string, unknown>)._is_admin as boolean

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="font-semibold text-gray-100">Analytics</h1>
        {viewer ? (
          isAdmin ? (
            <span className="flex items-center gap-1.5 text-xs text-brand-400 bg-brand-900/20 border border-brand-800/40 px-2 py-1 rounded-full">
              <ShieldCheck size={12} /> All users
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-gray-400 bg-gray-800 px-2 py-1 rounded-full">
              <User size={12} /> {viewer}
            </span>
          )
        ) : null}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard label="Total Traces" value={summary.total_traces ?? 0} />
        <StatCard label="Successful" value={summary.successful_traces ?? 0} />
        <StatCard label="Total Tokens" value={summary.total_tokens ?? 0} />
        <StatCard label="Tool Calls" value={summary.total_tool_calls ?? 0} />
        <StatCard label="Failed Tools" value={summary.failed_tool_calls ?? 0} />
        <StatCard label="RAG Docs" value={summary.rag_documents ?? 0} />
      </div>

      {/* Daily tokens */}
      <div className="bg-gray-900 rounded-xl p-5">
        <div className="text-sm font-medium text-gray-300 mb-4">Daily Token Usage</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={dailyTokens as Record<string, unknown>[]}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#6b7280' }} />
            <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} />
            <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }} />
            <Line type="monotone" dataKey="total_tokens" stroke="#0ea5e9" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Tool success rates */}
      <div className="bg-gray-900 rounded-xl p-5">
        <div className="text-sm font-medium text-gray-300 mb-4">Tool Success Rates</div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={(toolRates as Record<string, unknown>[]).slice(0, 15)}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="tool_name" tick={{ fontSize: 10, fill: '#6b7280' }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#6b7280' }} />
            <Tooltip contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }} />
            <Bar dataKey="success_rate_pct" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
