import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import Badge from '../components/Badge'

interface ToolCall {
  id: string
  span_id: string
  tool_name: string
  tool_source: string | null
  success: boolean
  error_type: string | null
  healing_strategy: string | null
  duration_ms: number | null
  retries: number
  known_fix_applied: boolean
  created_at: string
}

export default function Tools() {
  const { data = [], isLoading } = useQuery({
    queryKey: ['tool-calls'],
    queryFn: () => api.tools('limit=100') as Promise<ToolCall[]>,
    refetchInterval: 5000,
  })

  const failures = data.filter(t => !t.success).length
  const withFix = data.filter(t => t.known_fix_applied).length
  const avgLatency = data.length ? Math.round(data.reduce((s, t) => s + (t.duration_ms ?? 0), 0) / data.length) : 0

  return (
    <div className="h-full flex flex-col">
      <div className="h-14 px-6 flex items-center border-b border-gray-800">
        <h1 className="font-semibold text-gray-100">Tools</h1>
      </div>

      {/* Mini stats */}
      <div className="px-6 py-4 grid grid-cols-4 gap-3">
        {[
          { label: 'Total Calls', value: data.length },
          { label: 'Failures', value: failures },
          { label: 'Self-Healed', value: withFix },
          { label: 'Avg Latency', value: `${avgLatency}ms` },
        ].map(s => (
          <div key={s.label} className="bg-gray-900 rounded-lg p-3">
            <div className="text-xs text-gray-500">{s.label}</div>
            <div className="text-lg font-semibold text-gray-100 mt-0.5">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-gray-600">Loading...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase">
                <th className="px-6 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-left">Tool</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Heal</th>
                <th className="px-4 py-3 text-right">Retries</th>
                <th className="px-4 py-3 text-right">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map(t => (
                <tr key={t.id} className="hover:bg-gray-900/50 transition-colors">
                  <td className="px-6 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                    {new Date(t.created_at).toLocaleTimeString()}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-200">{t.tool_name}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 truncate max-w-24">{t.tool_source ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <Badge variant={t.success ? 'green' : 'red'}>{t.success ? 'ok' : t.error_type ?? 'fail'}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    {t.known_fix_applied
                      ? <Badge variant="yellow">{t.healing_strategy ?? 'fixed'}</Badge>
                      : <span className="text-gray-700">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">{t.retries}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">
                    {t.duration_ms != null ? `${t.duration_ms}ms` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
