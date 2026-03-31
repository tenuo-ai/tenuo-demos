import { useEffect, useRef, useState } from 'react'
import { fetchAgentLogs } from '../lib/api'
import type { AgentLog } from '../lib/types'

// Agent color scheme
const AGENT_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  'system':              { text: 'text-gray-400',   bg: 'bg-gray-800/50',   border: 'border-gray-700' },
  'finance-controller':  { text: 'text-blue-400',   bg: 'bg-blue-950/30',   border: 'border-blue-800' },
  'invoice-processor':   { text: 'text-purple-400', bg: 'bg-purple-950/30', border: 'border-purple-800' },
  'payment-executor':    { text: 'text-amber-400',  bg: 'bg-amber-950/30',  border: 'border-amber-800' },
  'expense-reviewer':    { text: 'text-cyan-400',   bg: 'bg-cyan-950/30',   border: 'border-cyan-800' },
  'vendor-verification': { text: 'text-green-400',  bg: 'bg-green-950/30',  border: 'border-green-800' },
  'fx-rate-checker':     { text: 'text-orange-400', bg: 'bg-orange-950/30', border: 'border-orange-800' },
}

function getColors(agentId: string) {
  return AGENT_COLORS[agentId] || AGENT_COLORS['system']
}

function EventIcon({ type }: { type: string }) {
  switch (type) {
    case 'thinking':      return <span title="Agent reasoning">💭</span>
    case 'tool_call':     return <span title="Tool call">🔧</span>
    case 'tool_result':   return <span title="Tool result">📋</span>
    case 'delegation':    return <span title="Delegation">🔀</span>
    case 'tenuo_block':   return <span title="Tenuo blocked">🛡</span>
    case 'status':        return <span title="Status">📌</span>
    default:              return <span>•</span>
  }
}

export function ToolCallLog() {
  const [logs, setLogs] = useState<AgentLog[]>([])
  const [filter, setFilter] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await fetchAgentLogs(filter || undefined)
        setLogs(data)
      } catch {
        // ignore
      }
    }
    poll()
    const interval = setInterval(poll, 1500)
    return () => clearInterval(interval)
  }, [filter])

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  // Get unique agent IDs for filter buttons
  const agents = [...new Set(logs.map((l) => l.agent_id))].filter((a) => a !== 'system')

  return (
    <div className="p-4 flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
          Activity Log
        </h2>
        <div className="flex gap-1">
          <button
            onClick={() => setFilter(null)}
            className={`px-2 py-0.5 text-xs rounded ${
              filter === null ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'
            }`}
          >
            all
          </button>
          {agents.map((agent) => {
            const colors = getColors(agent)
            return (
              <button
                key={agent}
                onClick={() => setFilter(filter === agent ? null : agent)}
                className={`px-2 py-0.5 text-xs rounded ${
                  filter === agent
                    ? `${colors.bg} ${colors.text} border ${colors.border}`
                    : 'bg-gray-800 text-gray-500 hover:bg-gray-700'
                }`}
              >
                {agent.split('-')[0]}
              </button>
            )
          })}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-1 min-h-0">
        {logs.map((log) => {
          const colors = getColors(log.agent_id)
          const isAttackTool = log.tool_name === 'update_vendor_bank'

          return (
            <div
              key={log.id}
              className={`text-xs px-2 py-1.5 rounded border-l-2 ${
                log.event_type === 'tenuo_block'
                  ? 'bg-green-950/40 border-l-green-500'
                  : isAttackTool
                  ? 'bg-red-950/40 border-l-red-500'
                  : `${colors.bg} ${colors.border}`
              }`}
            >
              <div className="flex items-start gap-1.5">
                <EventIcon type={log.event_type} />
                <span className={`font-medium ${isAttackTool ? 'text-red-400' : colors.text}`}>
                  {log.agent_id}
                </span>
                <span className="text-gray-600">
                  {new Date(log.created_at).toLocaleTimeString()}
                </span>
              </div>

              {log.event_type === 'thinking' && log.content && (
                <div className="mt-1 text-gray-300 leading-relaxed whitespace-pre-wrap">
                  {log.content.length > 300 ? log.content.slice(0, 300) + '...' : log.content}
                </div>
              )}

              {log.event_type === 'tenuo_block' && (
                <div className="mt-1">
                  <span className="text-green-400 font-semibold">🛡 {log.tool_name}</span>
                  <span className="text-green-600 ml-1 text-[10px]">not in task delegation</span>
                </div>
              )}

              {log.event_type === 'tool_call' && (
                <div className="mt-1">
                  <span className={isAttackTool ? 'text-red-400 font-bold' : 'text-green-400'}>
                    {log.tool_name}
                  </span>
                  <span className="text-gray-600 ml-1">
                    ({log.tool_args ? JSON.stringify(log.tool_args).slice(0, 80) : ''})
                  </span>
                  {isAttackTool && (
                    <span className="ml-2 text-red-500 font-medium">⚠ ATTACK</span>
                  )}
                </div>
              )}

              {log.event_type === 'tool_result' && (
                <div className="mt-1 text-gray-500">
                  <span className="text-gray-600">{log.tool_name} →</span>{' '}
                  {log.content && log.content.length > 150
                    ? log.content.slice(0, 150) + '...'
                    : log.content}
                </div>
              )}

              {log.event_type === 'delegation' && (
                <div className="mt-1 text-blue-300">
                  {log.content}
                </div>
              )}

              {log.event_type === 'status' && (
                <div className="mt-1 text-gray-400">
                  {log.content}
                </div>
              )}
            </div>
          )
        })}
        {logs.length === 0 && (
          <div className="text-gray-600 text-sm py-8 text-center">
            Click "Process Batch" to start the agent pipeline.
          </div>
        )}
      </div>
    </div>
  )
}
