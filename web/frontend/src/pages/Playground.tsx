import { useState, useRef, useEffect } from 'react'
import { Send, Loader2 } from 'lucide-react'
import { api } from '../api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  ts: string
}

export default function Playground() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
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

  return (
    <div className="flex flex-col h-full">
      <div className="h-14 px-6 flex items-center border-b border-gray-800">
        <h1 className="font-semibold text-gray-100">Playground</h1>
        <span className="ml-3 text-xs text-gray-500">Chat with the agent in real-time</span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
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
