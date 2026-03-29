import { useEffect, useState } from 'react'
import { fetchAuthDecisions } from '../lib/api'
import type { DemoEvent } from '../lib/types'

interface AuthRecord {
  request_id: string
  agent_id: string
  tool_name: string
  layer: string
  decision: string
  reason: string
  latency_us: number
}

// Group decisions by request_id, sort attack targets to top
function groupByRequest(records: AuthRecord[]) {
  const groups: Record<string, AuthRecord[]> = {}
  for (const r of records) {
    if (!groups[r.request_id]) groups[r.request_id] = []
    groups[r.request_id].push(r)
  }
  const entries = Object.entries(groups)
  // Sort: attack target tools first, then by recency
  entries.sort(([, a], [, b]) => {
    const aIsAttack = a.some((r) => r.tool_name === 'update_vendor_bank')
    const bIsAttack = b.some((r) => r.tool_name === 'update_vendor_bank')
    if (aIsAttack && !bIsAttack) return -1
    if (!aIsAttack && bIsAttack) return 1
    return 0
  })
  return entries.slice(0, 10)
}

const LAYER_ORDER = ['gcp_sa', 'oauth', 'spicedb', 'opa', 'tenuo']
const LAYER_LABELS: Record<string, string> = {
  gcp_sa: 'GCP SA',
  oauth: 'OAuth',
  spicedb: 'SpiceDB',
  opa: 'OPA',
  tenuo: 'Tenuo',
}

export function AuthDecisionPanel({ events }: { events: DemoEvent[] }) {
  const [records, setRecords] = useState<AuthRecord[]>([])

  // Poll for auth decisions
  useEffect(() => {
    const poll = async () => {
      try {
        const data = await fetchAuthDecisions()
        setRecords(data)
      } catch {
        // ignore
      }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  const grouped = groupByRequest(records)

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
        Auth Decisions
      </h2>
      <div className="space-y-3">
        {grouped.map(([requestId, decisions]) => {
          const first = decisions[0]
          const isAttackTool = first.tool_name === 'update_vendor_bank'

          return (
            <div
              key={requestId}
              className={`p-3 rounded border ${
                isAttackTool
                  ? 'border-red-800 bg-red-950/30'
                  : 'border-gray-800 bg-gray-900'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">
                  <span className="text-gray-500">{first.agent_id}</span>
                  {' → '}
                  <span className={isAttackTool ? 'text-red-400' : 'text-blue-400'}>
                    {first.tool_name}
                  </span>
                </span>
              </div>
              <div className="flex gap-2">
                {LAYER_ORDER.map((layer) => {
                  const d = decisions.find((r) => r.layer === layer)
                  if (!d) return null
                  return (
                    <div
                      key={layer}
                      className={`flex-1 px-2 py-1 rounded text-xs text-center ${
                        d.decision === 'allow'
                          ? isAttackTool
                            ? 'bg-green-900/50 text-green-400 border border-green-800'
                            : 'bg-green-900/30 text-green-500'
                          : 'bg-red-900/50 text-red-400 border border-red-800'
                      }`}
                      title={d.reason}
                    >
                      <div className="font-medium">{LAYER_LABELS[layer]}</div>
                      <div>{d.decision === 'allow' ? '✓' : '✗'}</div>
                      <div className="text-gray-600">{d.latency_us}μs</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
        {grouped.length === 0 && (
          <div className="text-gray-600 text-sm">No auth decisions yet. Start a batch to see results.</div>
        )}
      </div>
    </div>
  )
}
