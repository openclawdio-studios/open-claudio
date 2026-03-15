import { useQuery } from '@tanstack/react-query'
import { BookOpen, FileText } from 'lucide-react'
import { api } from '../api'
import Badge from '../components/Badge'

interface RagDoc {
  id: string
  source: string
  doc_type: string
  format: string | null
  chunk_count: number
  word_count_approx: number | null
  ingested_at: string
  deleted_at: string | null
}

export default function KnowledgeBase() {
  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['rag-documents'],
    queryFn: () => api.rag.documents() as Promise<RagDoc[]>,
    refetchInterval: 15_000,
  })
  const { data: retrievals = [] } = useQuery({
    queryKey: ['rag-retrievals'],
    queryFn: () => api.rag.retrievals() as Promise<Record<string, unknown>[]>,
  })

  const totalChunks = docs.reduce((s, d) => s + d.chunk_count, 0)
  const totalWords = docs.reduce((s, d) => s + (d.word_count_approx ?? 0), 0)

  return (
    <div className="p-6 space-y-6">
      <h1 className="font-semibold text-gray-100">Knowledge Base</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">Documents</div>
          <div className="text-2xl font-semibold text-gray-100">{docs.length}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">Total Chunks</div>
          <div className="text-2xl font-semibold text-gray-100">{totalChunks.toLocaleString()}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">~Total Words</div>
          <div className="text-2xl font-semibold text-gray-100">{(totalWords / 1000).toFixed(1)}k</div>
        </div>
      </div>

      {/* Documents table */}
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 flex items-center gap-2">
          <BookOpen size={14} className="text-brand-400" />
          <span className="text-sm font-medium text-gray-300">Ingested Documents</span>
        </div>
        {isLoading ? (
          <div className="p-8 text-center text-gray-600">Loading...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase">
                <th className="px-5 py-2 text-left">Source</th>
                <th className="px-4 py-2 text-left">Format</th>
                <th className="px-4 py-2 text-right">Chunks</th>
                <th className="px-4 py-2 text-right">~Words</th>
                <th className="px-4 py-2 text-left">Ingested</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {docs.map(d => (
                <tr key={d.id} className="hover:bg-gray-800/50">
                  <td className="px-5 py-2.5 flex items-center gap-2">
                    <FileText size={13} className="text-gray-500 flex-shrink-0" />
                    <span className="text-gray-300 font-mono text-xs truncate max-w-xs">{d.source}</span>
                  </td>
                  <td className="px-4 py-2.5"><Badge variant="blue">{d.format ?? d.doc_type}</Badge></td>
                  <td className="px-4 py-2.5 text-right text-gray-400 tabular-nums">{d.chunk_count}</td>
                  <td className="px-4 py-2.5 text-right text-gray-400 tabular-nums">{d.word_count_approx ? `${(d.word_count_approx / 1000).toFixed(1)}k` : '—'}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{new Date(d.ingested_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent retrievals */}
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
          Recent Retrievals ({retrievals.length})
        </div>
        <div className="divide-y divide-gray-800">
          {(retrievals as Record<string, unknown>[]).slice(0, 10).map((r, i) => (
            <div key={i} className="px-5 py-3 flex items-center gap-4 text-sm">
              <span className="text-gray-300 flex-1 truncate">{String(r.query)}</span>
              <Badge variant="gray">{String(r.results_count)} results</Badge>
              <span className="text-xs text-gray-500">{r.latency_ms ? `${Number(r.latency_ms).toFixed(0)}ms` : '—'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
