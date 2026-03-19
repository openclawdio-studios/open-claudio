import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import Badge from '../components/Badge'

interface Trace {
  id: string
  source: string
  status: string
  started_at: string | null
  ended_at: string | null
  input_text: string | null
  total_tokens: number | null
  user: string | null
}

function statusVariant(s: string) {
  if (s === 'ok') return 'green'
  if (s === 'error') return 'red'
  return 'yellow'
}

function duration(t: Trace): string {
  if (!t.started_at || !t.ended_at) return '—'
  const ms = new Date(t.ended_at).getTime() - new Date(t.started_at).getTime()
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

export default function Traces() {
  const { data = [], isLoading } = useQuery({
    queryKey: ['traces'],
    queryFn: () => api.traces('limit=100') as Promise<Trace[]>,
    refetchInterval: 5000,
  })

  return (
    <div className="h-full flex flex-col">
      <div className="h-14 px-6 flex items-center border-b border-gray-800">
        <h1 className="font-semibold text-gray-100">Traces</h1>
        <span className="ml-auto text-xs text-gray-500">{data.length} traces</span>
      </div>
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-gray-600">Loading...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase">
                <th className="px-6 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">User</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Input</th>
                <th className="px-4 py-3 text-right">Tokens</th>
                <th className="px-4 py-3 text-right">Duration</th>
                <th className="px-4 py-3 text-left">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map(t => (
                <tr key={t.id} className="hover:bg-gray-900/50 transition-colors">
                  <td className="px-6 py-3">
                    <Link to={`/traces/${t.id}`} className="font-mono text-xs text-brand-400 hover:underline">
                      {t.id.slice(0, 8)}...
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 font-mono">
                    {t.user ?? <span className="text-gray-700">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="blue">{t.source}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(t.status) as 'green' | 'red' | 'yellow'}>{t.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-gray-400 max-w-xs truncate">{t.input_text ?? '—'}</td>
                  <td className="px-4 py-3 text-right text-gray-400 tabular-nums">{t.total_tokens ?? '—'}</td>
                  <td className="px-4 py-3 text-right text-gray-400 tabular-nums">{duration(t)}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {t.started_at ? new Date(t.started_at).toLocaleString() : '—'}
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
