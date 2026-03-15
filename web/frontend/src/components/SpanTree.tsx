import { clsx } from 'clsx'

interface Span {
  id: string
  parent_span_id: string | null
  name: string
  kind: string
  status: string
  started_at: string | null
  ended_at: string | null
}

function duration(s: Span): string {
  if (!s.started_at || !s.ended_at) return '—'
  const ms = new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`
}

function buildTree(spans: Span[]): Map<string | null, Span[]> {
  const map = new Map<string | null, Span[]>()
  for (const s of spans) {
    const pid = s.parent_span_id ?? null
    if (!map.has(pid)) map.set(pid, [])
    map.get(pid)!.push(s)
  }
  return map
}

function SpanNode({ span, tree, depth }: { span: Span; tree: Map<string | null, Span[]>; depth: number }) {
  const children = tree.get(span.id) ?? []
  return (
    <div>
      <div
        className={clsx(
          'flex items-center gap-2 py-1.5 px-2 rounded hover:bg-gray-800 text-sm',
          depth > 0 && 'ml-4'
        )}
      >
        <span className="text-gray-500">{'  '.repeat(depth)}{'└─'}</span>
        <span className={clsx('font-mono text-xs px-1.5 py-0.5 rounded', span.kind === 'llm' ? 'bg-purple-900/40 text-purple-300' : span.kind === 'tool' ? 'bg-orange-900/40 text-orange-300' : 'bg-blue-900/40 text-blue-300')}>
          {span.kind}
        </span>
        <span className="text-gray-200 flex-1">{span.name}</span>
        <span className={clsx('text-xs', span.status === 'ok' ? 'text-green-400' : 'text-red-400')}>{span.status}</span>
        <span className="text-xs text-gray-500 w-16 text-right">{duration(span)}</span>
      </div>
      {children.map(c => <SpanNode key={c.id} span={c} tree={tree} depth={depth + 1} />)}
    </div>
  )
}

export default function SpanTree({ spans }: { spans: Span[] }) {
  const tree = buildTree(spans)
  const roots = tree.get(null) ?? []
  return (
    <div className="font-mono">
      {roots.map(r => <SpanNode key={r.id} span={r} tree={tree} depth={0} />)}
    </div>
  )
}
