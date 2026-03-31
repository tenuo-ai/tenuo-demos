/**
 * Warrant Chain view — shows warrants issued as agents delegate.
 *
 * Displays the 3-level delegation hierarchy with the actual
 * constraints on each warrant, so the audience can see exactly
 * what each agent is allowed to do.
 */
import { useEffect, useState } from 'react'
import { fetchWarrantChain } from '../lib/api'

interface WarrantEvent {
  agent_id: string
  details: string  // JSON string
  metadata: { warrant_type: string; tools: string[] } | null
  created_at: string
}

const AGENT_COLORS: Record<string, string> = {
  'finance-controller': 'border-blue-700 bg-blue-950/30',
  'invoice-processor': 'border-purple-700 bg-purple-950/30',
  'payment-executor': 'border-amber-700 bg-amber-950/30',
}
const AGENT_TEXT: Record<string, string> = {
  'finance-controller': 'text-blue-400',
  'invoice-processor': 'text-purple-400',
  'payment-executor': 'text-amber-400',
}

export function WarrantChain() {
  const [warrants, setWarrants] = useState<WarrantEvent[]>([])

  useEffect(() => {
    const poll = async () => {
      try {
        setWarrants(await fetchWarrantChain())
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  if (warrants.length === 0) return null

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
        Warrant Delegation Chain
      </h2>

      <div className="space-y-2">
        {warrants.map((w, i) => {
          let details: Record<string, unknown> = {}
          try { details = JSON.parse(w.details) } catch { /* ignore */ }

          const level = details.level as number || 0
          const tools = (details.tools as string[]) || w.metadata?.tools || []
          const removed = (details.removed as string[]) || []
          const constraints = details.constraints
          const ttl = details.ttl_seconds as number || 0
          const parent = details.parent as string || ''
          const invoiceId = details.invoice_id as string || ''
          const vendorId = details.vendor_id as string || ''

          const colors = AGENT_COLORS[w.agent_id] || 'border-gray-700 bg-gray-900'
          const textColor = AGENT_TEXT[w.agent_id] || 'text-gray-400'
          const indent = level > 1 ? 'ml-6' : ''

          return (
            <div key={i} className={`${indent}`}>
              {/* Connection line */}
              {level > 1 && (
                <div className="flex items-center gap-1 mb-1 ml-2">
                  <div className="w-4 border-b border-gray-700" />
                  <span className="text-[10px] text-gray-600">
                    attenuated by {parent}
                    {invoiceId && ` for ${invoiceId}`}
                  </span>
                </div>
              )}

              <div className={`rounded border p-3 ${colors}`}>
                {/* Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-600">L{level}</span>
                    <span className={`text-sm font-medium ${textColor}`}>
                      {w.agent_id}
                    </span>
                  </div>
                  <span className="text-[10px] text-gray-600">
                    TTL: {ttl < 60 ? `${ttl}s` : `${Math.round(ttl / 60)}m`}
                  </span>
                </div>

                {/* Tools */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {tools.map((t) => (
                    <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
                      {t}
                    </span>
                  ))}
                  {removed.map((t) => (
                    <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/50 text-red-400 line-through">
                      {t}
                    </span>
                  ))}
                </div>

                {/* Constraints */}
                {constraints && typeof constraints === 'object' && constraints !== null && typeof constraints !== 'string' && (
                  <div className="text-[10px] bg-gray-950/50 rounded p-2 font-mono">
                    {Object.entries(constraints as Record<string, unknown>).map(([tool, cons]) => (
                      <div key={tool} className="mb-1">
                        <span className="text-green-400">{tool}</span>:
                        {typeof cons === 'object' && cons !== null ? (
                          <div className="pl-3">
                            {Object.entries(cons as Record<string, string>).map(([key, val]) => (
                              <div key={key}>
                                <span className="text-gray-500">{key}:</span>{' '}
                                <span className={
                                  val.startsWith('Exact') ? 'text-blue-400' :
                                  val.startsWith('Range') ? 'text-yellow-400' :
                                  val.startsWith('OneOf') ? 'text-cyan-400' :
                                  'text-gray-400'
                                }>{val}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-500 ml-1">{String(cons)}</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {constraints === 'unconstrained' && (
                  <div className="text-[10px] text-gray-600 italic">All tools unconstrained</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
