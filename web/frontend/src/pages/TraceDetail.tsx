import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { api } from '../api'
import SpanTree from '../components/SpanTree'
import Badge from '../components/Badge'

interface LLMCall {
  id: string
  model: string
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  duration_ms: number | null
  stop_reason: string | null
  response_text: string | null
  created_at: string | null
}

interface ToolCall {
  id: string
  tool_name: string
  tool_source: string | null
  arguments: Record<string, unknown> | null
  result: string | null
  success: boolean
  error_type: string | null
  duration_ms: number | null
  retries: number
  known_fix_applied: boolean
  created_at: string | null
}

export default function TraceDetail() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, error } = useQuery({
    queryKey: ['trace', id],
    queryFn: () => api.trace(id!) as Promise<Record<string, unknown>>,
    enabled: !!id,
  })

  if (isLoading) return <div className="p-8 text-gray-500">Loading...</div>
  if (error || !data) return <div className="p-8 text-red-400">Failed to load trace.</div>

  const trace = data as Record<string, unknown>
  const spans = (trace.spans as unknown[]) ?? []
  const llmCalls = (trace.llm_calls as LLMCall[]) ?? []
  const toolCalls = (trace.tool_calls as ToolCall[]) ?? []

  const totalPrompt = llmCalls.reduce((s, c) => s + (c.prompt_tokens ?? 0), 0)
  const totalCompletion = llmCalls.reduce((s, c) => s + (c.completion_tokens ?? 0), 0)
  const durationMs = trace.duration_ms as number | null

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/traces" className="text-gray-500 hover:text-gray-300"><ArrowLeft size={18} /></Link>
        <h1 className="font-semibold text-gray-100">Trace <span className="font-mono text-brand-400">{String(trace.id).slice(0, 8)}...</span></h1>
        <Badge variant={trace.status === 'ok' ? 'green' : trace.status === 'running' ? 'yellow' : 'red'}>{String(trace.status)}</Badge>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { label: 'Source', value: String(trace.source) },
          { label: 'Prompt tokens', value: totalPrompt.toLocaleString() },
          { label: 'Completion tokens', value: totalCompletion.toLocaleString() },
          { label: 'LLM Calls', value: String(llmCalls.length) },
          { label: 'Duration', value: durationMs != null ? durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s` : '—' },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-900 rounded-xl p-4">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className="text-xl font-semibold text-gray-100">{value}</div>
          </div>
        ))}
      </div>

      {/* Input / Output */}
      {(trace.input_text || trace.output_text) && (
        <div className="grid grid-cols-2 gap-4">
          {trace.input_text && (
            <div className="bg-gray-900 rounded-xl p-4">
              <div className="text-xs text-gray-500 mb-2">Input</div>
              <p className="text-sm text-gray-300 whitespace-pre-wrap">{String(trace.input_text)}</p>
            </div>
          )}
          {trace.output_text && (
            <div className="bg-gray-900 rounded-xl p-4">
              <div className="text-xs text-gray-500 mb-2">Output</div>
              <p className="text-sm text-gray-300 whitespace-pre-wrap">{String(trace.output_text)}</p>
            </div>
          )}
        </div>
      )}

      {/* Span Tree */}
      <div className="bg-gray-900 rounded-xl p-4">
        <div className="text-xs text-gray-500 mb-3">Span Tree ({spans.length} spans)</div>
        <SpanTree spans={spans as Parameters<typeof SpanTree>[0]['spans']} />
      </div>

      {/* LLM Calls per step */}
      {llmCalls.length > 0 && (
        <div className="bg-gray-900 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
            LLM Calls — tokens per step
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase">
                <th className="px-5 py-2 text-left">Step</th>
                <th className="px-4 py-2 text-left">Model</th>
                <th className="px-4 py-2 text-right">Prompt</th>
                <th className="px-4 py-2 text-right">Completion</th>
                <th className="px-4 py-2 text-right">Total</th>
                <th className="px-4 py-2 text-right">Latency</th>
                <th className="px-4 py-2 text-left">Stop</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {llmCalls.map((c, i) => (
                <tr key={c.id} className="hover:bg-gray-800/50">
                  <td className="px-5 py-2.5 text-gray-500 text-xs">#{i + 1}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{c.model}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-300">{c.prompt_tokens?.toLocaleString() ?? '—'}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-300">{c.completion_tokens?.toLocaleString() ?? '—'}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-medium text-gray-100">
                    {c.prompt_tokens != null && c.completion_tokens != null
                      ? (c.prompt_tokens + c.completion_tokens).toLocaleString()
                      : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">
                    {c.duration_ms != null ? `${c.duration_ms}ms` : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge variant={c.stop_reason === 'stop' ? 'green' : 'blue'}>{c.stop_reason ?? '—'}</Badge>
                  </td>
                </tr>
              ))}
              {/* Totals row */}
              <tr className="border-t-2 border-gray-700 bg-gray-800/30">
                <td className="px-5 py-2.5 text-xs text-gray-500 font-medium" colSpan={2}>Total</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-brand-400 font-medium">{totalPrompt.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-brand-400 font-medium">{totalCompletion.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-brand-400 font-bold">{(totalPrompt + totalCompletion).toLocaleString()}</td>
                <td className="px-4 py-2.5" colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Tool Calls */}
      {toolCalls.length > 0 && (
        <div className="bg-gray-900 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
            Tool Calls ({toolCalls.length})
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase">
                <th className="px-5 py-2 text-left">Tool</th>
                <th className="px-4 py-2 text-left">Source</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Retries</th>
                <th className="px-4 py-2 text-right">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {toolCalls.map(c => (
                <tr key={c.id} className="hover:bg-gray-800/50">
                  <td className="px-5 py-2.5 font-mono text-xs text-gray-200">{c.tool_name}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{c.tool_source ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <Badge variant={c.success ? 'green' : 'red'}>{c.success ? 'ok' : c.error_type ?? 'error'}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">{c.retries}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-400">
                    {c.duration_ms != null ? `${c.duration_ms}ms` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
