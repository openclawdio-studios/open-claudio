import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Users as UsersIcon, Plus, Key, Trash2, ChevronDown, ChevronRight,
  Copy, CheckCircle, XCircle, Loader2, ShieldCheck, Lock,
} from 'lucide-react'
import { clsx } from 'clsx'
import Badge from '../components/Badge'
import { api, AdminUser, ApiKeyInfo, ApiKeyCreated, getApiKey, setApiKey } from '../api'

// ── API key gate ──────────────────────────────────────────────────────────────
function ApiKeyGate({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState('')
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <Lock size={32} className="text-gray-600" />
      <p className="text-gray-400 text-sm">Enter your admin API key to access this page</p>
      <div className="flex gap-2 w-80">
        <input
          type="password"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
          placeholder="clau-..."
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && value) { setApiKey(value); onSaved() } }}
        />
        <button
          disabled={!value}
          onClick={() => { setApiKey(value); onSaved() }}
          className="px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm rounded-lg"
        >
          Save
        </button>
      </div>
    </div>
  )
}

// ── Create user modal ────────────────────────────────────────────────────────
interface CreateUserModalProps { onClose: () => void }
function CreateUserModal({ onClose }: CreateUserModalProps) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [dailyTokens, setDailyTokens] = useState('100000')
  const [isAdmin, setIsAdmin] = useState(false)

  const mut = useMutation({
    mutationFn: () => api.admin.createUser({
      username,
      display_name: displayName || undefined,
      daily_tokens: parseInt(dailyTokens) || -1,
      is_admin: isAdmin,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); onClose() },
  })

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-96 space-y-4">
        <h2 className="font-semibold text-gray-100">Create user</h2>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Username *</label>
            <input value={username} onChange={e => setUsername(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
              placeholder="alice" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Display name</label>
            <input value={displayName} onChange={e => setDisplayName(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
              placeholder="Alice Smith" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Daily token limit (-1 = unlimited)</label>
            <input value={dailyTokens} onChange={e => setDailyTokens(e.target.value)}
              type="number"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500" />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
            <input type="checkbox" checked={isAdmin} onChange={e => setIsAdmin(e.target.checked)}
              className="accent-brand-500" />
            Admin
          </label>
        </div>

        {mut.isError && (
          <p className="text-xs text-red-400">{(mut.error as Error).message}</p>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-100">Cancel</button>
          <button
            disabled={!username || mut.isPending}
            onClick={() => mut.mutate()}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm rounded-lg"
          >
            {mut.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
            Create
          </button>
        </div>
      </div>
    </div>
  )
}

// ── New key modal (shows key once) ────────────────────────────────────────────
interface NewKeyModalProps { userId: string; onClose: () => void }
function NewKeyModal({ userId, onClose }: NewKeyModalProps) {
  const qc = useQueryClient()
  const [keyName, setKeyName] = useState('API key')
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [copied, setCopied] = useState(false)

  const mut = useMutation({
    mutationFn: () => api.admin.createKey(userId, keyName),
    onSuccess: (data) => {
      setCreated(data)
      qc.invalidateQueries({ queryKey: ['admin-keys', userId] })
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })

  function copyKey() {
    if (!created) return
    navigator.clipboard.writeText(created.raw_key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-[480px] space-y-4">
        <h2 className="font-semibold text-gray-100">
          {created ? 'API key created' : 'New API key'}
        </h2>

        {!created ? (
          <>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Key name</label>
              <input value={keyName} onChange={e => setKeyName(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
                placeholder="Home CLI, Dashboard, etc." />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-100">Cancel</button>
              <button
                disabled={mut.isPending}
                onClick={() => mut.mutate()}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm rounded-lg"
              >
                {mut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Key size={14} />}
                Generate
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-800/40 rounded-lg px-3 py-2">
              Copy this key now — it will never be shown again.
            </p>
            <div className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-2">
              <code className="flex-1 text-xs text-green-300 break-all">{created.raw_key}</code>
              <button onClick={copyKey} className="text-gray-500 hover:text-gray-200 flex-shrink-0">
                {copied ? <CheckCircle size={15} className="text-green-400" /> : <Copy size={15} />}
              </button>
            </div>
            <div className="flex justify-end">
              <button onClick={onClose} className="px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white text-sm rounded-lg">
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Keys row ──────────────────────────────────────────────────────────────────
function KeysRow({ userId }: { userId: string }) {
  const qc = useQueryClient()
  const { data: keys = [], isLoading } = useQuery<ApiKeyInfo[]>({
    queryKey: ['admin-keys', userId],
    queryFn: () => api.admin.keys(userId),
  })

  const revoke = useMutation({
    mutationFn: (keyId: string) => api.admin.revokeKey(userId, keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-keys', userId] })
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })

  if (isLoading) return <div className="p-4 text-xs text-gray-600">Loading keys…</div>
  if (keys.length === 0) return <div className="p-4 text-xs text-gray-600">No active keys.</div>

  return (
    <div className="divide-y divide-gray-800">
      {keys.map(k => (
        <div key={k.id} className="px-6 py-2 flex items-center gap-4 text-xs">
          <code className="text-green-400 w-32">{k.key_prefix}…</code>
          <span className="text-gray-400 flex-1">{k.name || '—'}</span>
          <span className="text-gray-600">
            {k.last_used_at ? `last used ${new Date(k.last_used_at).toLocaleDateString()}` : 'never used'}
          </span>
          <span className="text-gray-600">
            created {new Date(k.created_at).toLocaleDateString()}
          </span>
          <button
            onClick={() => { if (confirm('Revoke this key?')) revoke.mutate(k.id) }}
            disabled={revoke.isPending}
            className="text-gray-600 hover:text-red-400 transition-colors"
            title="Revoke key"
          >
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Users() {
  const qc = useQueryClient()
  const [hasKey, setHasKey] = useState(!!getApiKey())
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newKeyFor, setNewKeyFor] = useState<string | null>(null)

  const { data: users = [], isLoading, error } = useQuery<AdminUser[]>({
    queryKey: ['admin-users'],
    queryFn: api.admin.users,
    enabled: hasKey,
    retry: false,
  })

  const deactivate = useMutation({
    mutationFn: api.admin.deactivateUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  if (!hasKey) return <ApiKeyGate onSaved={() => setHasKey(true)} />

  const errMsg = error ? (error as Error).message : null
  const is401 = errMsg?.includes('401')

  if (is401) return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <XCircle size={32} className="text-red-500" />
      <p className="text-gray-400 text-sm">Invalid or expired API key.</p>
      <button onClick={() => { localStorage.removeItem('claudio_api_key'); setHasKey(false) }}
        className="text-xs text-brand-400 hover:underline">
        Enter a different key
      </button>
    </div>
  )

  const is403 = errMsg?.includes('403')
  if (is403) return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <ShieldCheck size={32} className="text-yellow-500" />
      <p className="text-gray-400 text-sm">This key does not have admin access.</p>
    </div>
  )

  const totalUsers = users.length
  const activeUsers = users.filter(u => u.is_active).length
  const totalKeys = users.reduce((s, u) => s + u.api_keys_count, 0)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-semibold text-gray-100">Users</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-3 py-2 bg-brand-600 hover:bg-brand-700 text-white text-sm rounded-lg"
        >
          <Plus size={15} /> New user
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total users', value: totalUsers },
          { label: 'Active', value: activeUsers },
          { label: 'Active API keys', value: totalKeys },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-900 rounded-xl p-5">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className="text-2xl font-semibold text-gray-100">{value}</div>
          </div>
        ))}
      </div>

      {/* Users table */}
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-300">
          Users ({totalUsers})
        </div>

        {isLoading ? (
          <div className="p-8 text-center text-gray-600">Loading…</div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-gray-600">No users yet. Create one above.</div>
        ) : (
          <div className="divide-y divide-gray-800">
            {users.map(u => {
              const expanded = expandedId === u.id
              const quota = u.daily_tokens
              const pct = quota === -1 ? 0 : Math.min(100, (u.tokens_used_today / quota) * 100)
              const nearLimit = quota !== -1 && pct >= 80

              return (
                <div key={u.id}>
                  <div
                    className="px-5 py-3 flex items-center gap-4 hover:bg-gray-800/40 cursor-pointer"
                    onClick={() => setExpandedId(expanded ? null : u.id)}
                  >
                    {/* Expand chevron */}
                    <span className="text-gray-600 flex-shrink-0">
                      {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </span>

                    {/* Username */}
                    <div className="w-36 flex-shrink-0">
                      <div className="text-sm text-gray-200 font-medium flex items-center gap-1.5">
                        {u.is_admin && <ShieldCheck size={12} className="text-brand-400" />}
                        {u.username}
                      </div>
                      {u.display_name && (
                        <div className="text-xs text-gray-500">{u.display_name}</div>
                      )}
                    </div>

                    {/* Today's usage */}
                    <div className="flex-1">
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className={nearLimit ? 'text-yellow-400' : 'text-gray-500'}>
                          Today: {u.tokens_used_today.toLocaleString()} tokens
                        </span>
                        <span className="text-gray-600">
                          {quota === -1 ? 'unlimited' : `/ ${quota.toLocaleString()}`}
                        </span>
                      </div>
                      {quota !== -1 && (
                        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div
                            className={clsx(
                              'h-full rounded-full transition-all',
                              pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-yellow-500' : 'bg-brand-500'
                            )}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      )}
                    </div>

                    {/* Status */}
                    <div className="w-20 flex-shrink-0 text-right">
                      <Badge variant={u.is_active ? 'green' : 'gray'}>
                        {u.is_active ? 'active' : 'inactive'}
                      </Badge>
                    </div>

                    {/* Keys count */}
                    <div className="w-24 flex-shrink-0 text-right">
                      <button
                        onClick={e => { e.stopPropagation(); setNewKeyFor(u.id) }}
                        className="flex items-center gap-1 text-xs text-gray-500 hover:text-brand-400 ml-auto"
                        title="Add API key"
                      >
                        <Key size={12} />
                        {u.api_keys_count} key{u.api_keys_count !== 1 ? 's' : ''}
                      </button>
                    </div>

                    {/* Deactivate */}
                    {u.is_active && (
                      <button
                        onClick={e => {
                          e.stopPropagation()
                          if (confirm(`Deactivate user "${u.username}"?`)) deactivate.mutate(u.id)
                        }}
                        className="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0"
                        title="Deactivate user"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>

                  {/* Expanded keys panel */}
                  {expanded && (
                    <div className="bg-gray-950 border-t border-gray-800">
                      <div className="px-5 py-2 flex items-center justify-between border-b border-gray-800">
                        <span className="text-xs text-gray-500 uppercase tracking-wide">API Keys</span>
                        <button
                          onClick={() => setNewKeyFor(u.id)}
                          className="flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300"
                        >
                          <Plus size={12} /> Add key
                        </button>
                      </div>
                      <KeysRow userId={u.id} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Modals */}
      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
      {newKeyFor && <NewKeyModal userId={newKeyFor} onClose={() => setNewKeyFor(null)} />}
    </div>
  )
}
