import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, Trash2, FileText, Loader2, CheckCircle, XCircle } from 'lucide-react'
import { clsx } from 'clsx'
import Badge from '../components/Badge'

interface RagSource {
  source: string
  doc_type: string
  tags: string
  chunk_count: number
  timestamp: string
}

interface RagRetrieval {
  id: string
  query: string
  results_count: number
  duration_ms: number | null
  created_at: string
}

const DOC_TYPES = ['manual', 'config', 'preference', 'log', 'conversation', 'other']

async function fetchSources(): Promise<RagSource[]> {
  const r = await fetch('/api/rag/sources')
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function fetchRetrievals(): Promise<RagRetrieval[]> {
  const r = await fetch('/api/rag/retrievals?limit=10')
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function uploadFile(formData: FormData): Promise<Record<string, unknown>> {
  const r = await fetch('/api/rag/upload', { method: 'POST', body: formData })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function deleteSource(source: string): Promise<void> {
  const r = await fetch(`/api/rag/sources/${encodeURIComponent(source)}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
}

export default function KnowledgeBase() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [docType, setDocType] = useState('manual')
  const [tags, setTags] = useState('')
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; msg: string } | null>(null)

  const { data: sources = [], isLoading: loadingSources } = useQuery({
    queryKey: ['rag-sources'],
    queryFn: fetchSources,
    refetchInterval: 15_000,
  })

  const { data: retrievals = [] } = useQuery({
    queryKey: ['rag-retrievals'],
    queryFn: fetchRetrievals,
    refetchInterval: 30_000,
  })

  const uploadMutation = useMutation({
    mutationFn: uploadFile,
    onSuccess: (data) => {
      setUploadResult({ ok: true, msg: `Ingested ${data.chunks_ingested} chunks from "${data.source}"` })
      setSelectedFile(null)
      setTags('')
      qc.invalidateQueries({ queryKey: ['rag-sources'] })
    },
    onError: (e: Error) => {
      setUploadResult({ ok: false, msg: e.message })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rag-sources'] }),
  })

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) setSelectedFile(file)
  }, [])

  const handleSubmit = () => {
    if (!selectedFile) return
    setUploadResult(null)
    const fd = new FormData()
    fd.append('file', selectedFile)
    fd.append('doc_type', docType)
    fd.append('tags', tags)
    uploadMutation.mutate(fd)
  }

  const totalChunks = sources.reduce((s, d) => s + d.chunk_count, 0)

  return (
    <div className="p-6 space-y-6">
      <h1 className="font-semibold text-gray-100">Knowledge Base</h1>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">Documents</div>
          <div className="text-2xl font-semibold text-gray-100">{sources.length}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">Total Chunks</div>
          <div className="text-2xl font-semibold text-gray-100">{totalChunks.toLocaleString()}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-5">
          <div className="text-xs text-gray-500 mb-1">Recent Queries</div>
          <div className="text-2xl font-semibold text-gray-100">{retrievals.length}</div>
        </div>
      </div>

      {/* Upload panel */}
      <div className="bg-gray-900 rounded-xl p-5 space-y-4">
        <div className="text-sm font-medium text-gray-300">Upload document</div>

        {/* Drop zone */}
        <div
          className={clsx(
            'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors',
            dragging ? 'border-brand-500 bg-brand-900/20' : 'border-gray-700 hover:border-gray-500',
            selectedFile && 'border-green-700 bg-green-900/10'
          )}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".txt,.md,.markdown,.pdf"
            onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
          />
          {selectedFile ? (
            <div className="flex items-center justify-center gap-3">
              <FileText size={20} className="text-green-400" />
              <span className="text-sm text-green-300 font-medium">{selectedFile.name}</span>
              <span className="text-xs text-gray-500">({(selectedFile.size / 1024).toFixed(1)} KB)</span>
            </div>
          ) : (
            <div className="space-y-2">
              <Upload size={24} className="mx-auto text-gray-600" />
              <p className="text-sm text-gray-500">Drop a file here or click to browse</p>
              <p className="text-xs text-gray-700">.txt · .md · .pdf</p>
            </div>
          )}
        </div>

        {/* Options */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Document type</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
            >
              {DOC_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Tags (comma-separated)</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. zwave, blinds, salon"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500"
            />
          </div>
        </div>

        {/* Result */}
        {uploadResult && (
          <div className={clsx(
            'flex items-center gap-2 text-sm px-3 py-2 rounded-lg',
            uploadResult.ok ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
          )}>
            {uploadResult.ok
              ? <CheckCircle size={16} className="flex-shrink-0" />
              : <XCircle size={16} className="flex-shrink-0" />}
            {uploadResult.msg}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!selectedFile || uploadMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {uploadMutation.isPending
            ? <><Loader2 size={15} className="animate-spin" /> Ingesting...</>
            : <><Upload size={15} /> Ingest document</>}
        </button>
      </div>

      {/* Documents table */}
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
          Indexed documents ({sources.length})
        </div>
        {loadingSources ? (
          <div className="p-8 text-center text-gray-600">Loading...</div>
        ) : sources.length === 0 ? (
          <div className="p-8 text-center text-gray-600">No documents ingested yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase">
                <th className="px-5 py-2 text-left">Source</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Tags</th>
                <th className="px-4 py-2 text-right">Chunks</th>
                <th className="px-4 py-2 text-left">Ingested</th>
                <th className="px-4 py-2 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {sources.map((d) => (
                <tr key={d.source} className="hover:bg-gray-800/50">
                  <td className="px-5 py-2.5 flex items-center gap-2">
                    <FileText size={13} className="text-gray-500 flex-shrink-0" />
                    <span className="text-gray-300 font-mono text-xs truncate max-w-xs">{d.source}</span>
                  </td>
                  <td className="px-4 py-2.5"><Badge variant="blue">{d.doc_type}</Badge></td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 truncate max-w-32">{d.tags || '—'}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">{d.chunk_count}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">
                    {d.timestamp ? new Date(d.timestamp).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <button
                      onClick={() => { if (confirm(`Delete "${d.source}" from knowledge base?`)) deleteMutation.mutate(d.source) }}
                      disabled={deleteMutation.isPending}
                      className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-30"
                      title="Delete from knowledge base"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent retrievals */}
      {retrievals.length > 0 && (
        <div className="bg-gray-900 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
            Recent searches
          </div>
          <div className="divide-y divide-gray-800">
            {retrievals.map((r) => (
              <div key={r.id} className="px-5 py-3 flex items-center gap-4 text-sm">
                <span className="text-gray-300 flex-1 truncate">{r.query}</span>
                <Badge variant="gray">{r.results_count} results</Badge>
                <span className="text-xs text-gray-500 w-16 text-right">
                  {r.duration_ms != null ? `${r.duration_ms}ms` : '—'}
                </span>
                <span className="text-xs text-gray-600 w-32 text-right">
                  {new Date(r.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
