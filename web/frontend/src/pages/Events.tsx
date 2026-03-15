import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import Badge from '../components/Badge'

interface EventRow {
  id: string
  source: string
  event_type: string
  topic: string
  status: string
  payload: Record<string, unknown> | null
  received_at: string
  processed_at: string | null
}

export default function Events() {
  const { data = [], isLoading } = useQuery({
    queryKey: ['events'],
    queryFn: () => api.events('limit=100') as Promise<EventRow[]>,
    refetchInterval: 3000,
  })

  return (
    <div className="h-full flex flex-col">
      <div className="h-14 px-6 flex items-center border-b border-gray-800">
        <h1 className="font-semibold text-gray-100">Events</h1>
        <span className="ml-3 text-xs text-gray-500">Live feed</span>
        <span className="ml-auto text-xs text-gray-500">{data.length} events</span>
      </div>
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-gray-600">Loading...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase sticky top-0 bg-gray-950">
                <th className="px-6 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Topic</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map(e => (
                <tr key={e.id} className="hover:bg-gray-900/50 transition-colors">
                  <td className="px-6 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                    {new Date(e.received_at).toLocaleTimeString()}
                  </td>
                  <td className="px-4 py-2.5"><Badge variant="blue">{e.source}</Badge></td>
                  <td className="px-4 py-2.5 text-gray-400">{e.event_type}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{e.topic}</td>
                  <td className="px-4 py-2.5">
                    <Badge variant={e.status === 'processed' ? 'green' : e.status === 'error' ? 'red' : 'yellow'}>
                      {e.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-600 max-w-xs truncate">
                    {e.payload ? JSON.stringify(e.payload) : '—'}
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
