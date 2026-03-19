const BASE = '/api'

// ── API key storage ───────────────────────────────────────────────────────────
const KEY_STORE = 'claudio_api_key'

export function getApiKey(): string | null {
  return localStorage.getItem(KEY_STORE)
}

export function setApiKey(key: string) {
  localStorage.setItem(KEY_STORE, key)
}

export function clearApiKey() {
  localStorage.removeItem(KEY_STORE)
}

function authHeaders(): Record<string, string> {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────
async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function post<T>(path: string, body: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function authGet<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function authPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function authPut<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function authDelete<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

// ── Public API ────────────────────────────────────────────────────────────────
export const api = {
  chat: (message: string) =>
    authPost<{ status: string; response: string }>('/chat', { message }),

  traces: (params?: string) => authGet<unknown[]>(`/traces${params ? '?' + params : ''}`),
  trace: (id: string) => authGet<unknown>(`/traces/${id}`),

  analytics: {
    summary: () => authGet<Record<string, unknown>>('/analytics/summary'),
    dailyTokens: () => authGet<unknown[]>('/analytics/daily-tokens'),
    toolSuccessRates: () => authGet<unknown[]>('/analytics/tool-success-rates'),
    spanLatency: () => authGet<unknown[]>('/analytics/span-latency'),
  },

  events: (params?: string) => authGet<unknown[]>(`/events${params ? '?' + params : ''}`),
  tools: (params?: string) => get<unknown[]>(`/tools/calls${params ? '?' + params : ''}`),

  rag: {
    documents: () => get<unknown[]>('/rag/documents'),
    retrievals: () => get<unknown[]>('/rag/retrievals'),
  },

  admin: {
    users: () => authGet<AdminUser[]>('/admin/users'),
    createUser: (body: { username: string; display_name?: string; daily_tokens: number; is_admin: boolean }) =>
      authPost<{ id: string; username: string }>('/admin/users', body),
    updateUser: (id: string, body: { display_name?: string; is_active?: boolean; daily_tokens?: number }) =>
      authPut<{ status: string }>(`/admin/users/${id}`, body),
    deactivateUser: (id: string) =>
      authDelete<{ status: string }>(`/admin/users/${id}`),
    keys: (userId: string) => authGet<ApiKeyInfo[]>(`/admin/users/${userId}/keys`),
    createKey: (userId: string, name: string) =>
      authPost<ApiKeyCreated>(`/admin/users/${userId}/keys`, { name }),
    revokeKey: (userId: string, keyId: string) =>
      authDelete<{ status: string }>(`/admin/users/${userId}/keys/${keyId}`),
  },
}

// ── Types ─────────────────────────────────────────────────────────────────────
export interface AdminUser {
  id: string
  username: string
  display_name: string | null
  is_active: boolean
  is_admin: boolean
  created_at: string
  last_seen_at: string | null
  daily_tokens: number
  tokens_used_today: number
  api_keys_count: number
}

export interface ApiKeyInfo {
  id: string
  key_prefix: string
  name: string | null
  created_at: string
  last_used_at: string | null
}

export interface ApiKeyCreated extends ApiKeyInfo {
  raw_key: string
}
