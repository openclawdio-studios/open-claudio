import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Key } from 'lucide-react'
import { api, getApiKey, setApiKey } from '../api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  ts: string
}

export default function Playground() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showKeyInput, setShowKeyInput] = useState(false)
  const [keyDraft, setKeyDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    const ts = new Date().toISOString()
    setMessages(m => [...m, { role: 'user', content: text, ts }])
    setLoading(true)
    try {
      const res = await api.chat(text)
      setMessages(m => [
        ...m,
        { role: 'assistant', content: res.response ?? res.status, ts: new Date().toISOString() },
      ])
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setMessages(m => [...m, { role: 'assistant', content: `Error: ${msg}`, ts: new Date().toISOString() }])
    } finally {
      setLoading(false)
    }
  }

  const apiKey = getApiKey()

  return (
    <div className="flex flex-col h-full">
      <div className="h-14 px-6 flex items-center border-b border-gray-800 gap-4">
        <h1 className="font-semibold text-gray-100">Playground</h1>
        <span className="flex-1 text-xs text-gray-500">Chat with the agent in real-time</span>
        {showKeyInput ? (
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={keyDraft}
              onChange={e => setKeyDraft(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && keyDraft) { setApiKey(keyDraft); setKeyDraft(''); setShowKeyInput(false) }
                if (e.key === 'Escape') setShowKeyInput(false)
              }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 w-64 focus:outline-none focus:border-brand-500"
              placeholder="clau-..."
              autoFocus
            />
            <button
              disabled={!keyDraft}
              onClick={() => { setApiKey(keyDraft); setKeyDraft(''); setShowKeyInput(false) }}
              className="px-3 py-1.5 bg-brand-600 hover:bg-brand-700 disabled:bg-gray-800 text-white text-xs rounded-lg"
            >Save</button>
            <button onClick={() => setShowKeyInput(false)} className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
          </div>
        ) : (
          <button
            onClick={() => setShowKeyInput(true)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300"
            title={apiKey ? 'Change API key' : 'Set API key'}
          >
            <Key size={13} />
            {apiKey ? apiKey.slice(0, 13) + '…' : 'Set API key'}
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
        {!apiKey && (
          <div className="bg-yellow-900/20 border border-yellow-800/40 rounded-xl px-4 py-3 flex items-center gap-3 text-sm">
            <Key size={15} className="text-yellow-400 flex-shrink-0" />
            <span className="text-yellow-300">Set your API key (top-right) to start chatting.</span>
          </div>
        )}
        {messages.length === 0 && apiKey && (
          <div className="text-center text-gray-600 mt-20">
            <p className="text-lg">Ask the agent anything</p>
            <p className="text-sm mt-1">Commands, queries, home automation...</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-2xl rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-brand-600 text-white rounded-br-sm'
                  : 'bg-gray-800 text-gray-100 rounded-bl-sm'
              }`}
            >
              {m.content}
              <div className="text-xs opacity-40 mt-1">{new Date(m.ts).toLocaleTimeString()}</div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-3">
              <Loader2 size={16} className="animate-spin text-gray-400" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 pb-6 pt-2">
        <div className="flex gap-2 bg-gray-900 border border-gray-700 rounded-2xl px-4 py-3">
          <textarea
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-600 resize-none outline-none max-h-32"
            rows={1}
            placeholder="Send a message..."
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            className="self-end text-brand-500 hover:text-brand-400 disabled:text-gray-700 transition-colors"
          >
            <Send size={18} />
          </button>
        </div>
        <p className="text-xs text-gray-700 mt-1 text-center">Enter to send · Shift+Enter for newline</p>
      </div>
    </div>
  )
}
