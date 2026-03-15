const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const api = {
  chat: (message: string) => post<{ status: string; response: string }>('/chat', { message }),
  traces: (params?: string) => get<unknown[]>(`/traces${params ? '?' + params : ''}`),
  trace: (id: string) => get<unknown>(`/traces/${id}`),
  analytics: {
    summary: () => get<Record<string, number>>('/analytics/summary'),
    dailyTokens: () => get<unknown[]>('/analytics/daily-tokens'),
    toolSuccessRates: () => get<unknown[]>('/analytics/tool-success-rates'),
    spanLatency: () => get<unknown[]>('/analytics/span-latency'),
  },
  events: (params?: string) => get<unknown[]>(`/events${params ? '?' + params : ''}`),
  tools: (params?: string) => get<unknown[]>(`/tools/calls${params ? '?' + params : ''}`),
  rag: {
    documents: () => get<unknown[]>('/rag/documents'),
    retrievals: () => get<unknown[]>('/rag/retrievals'),
  },
}
