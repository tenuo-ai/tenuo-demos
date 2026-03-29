import { useEffect, useState } from 'react'
import { fetchAuthDecisions } from '../lib/api'

interface AuthRecord {
  request_id: string
  agent_id: string
  tool_name: string
  layer: string
  decision: string
  reason: string
  latency_us: number
}

const LAYER_ORDER = ['gcp_sa', 'oauth', 'spicedb', 'opa', 'tenuo']
const LAYER_LABELS: Record<string, string> = {
  gcp_sa: 'GCP SA',
  oauth: 'OAuth',
  spicedb: 'SpiceDB',
  opa: 'OPA',
  tenuo: 'Tenuo',
}

const ATTACK_TOOLS = new Set(['update_vendor_bank'])

// Group auth records into tool calls (by request_id), then into sections
function buildSections(records: AuthRecord[]) {
  // Group by request_id → one card per tool call
  const byRequest: Record<string, AuthRecord[]> = {}
  for (const r of records) {
    if (!byRequest[r.request_id]) byRequest[r.request_id] = []
    byRequest[r.request_id].push(r)
  }

  // Convert to array and sort: attacks first, then standard
  const calls = Object.values(byRequest).map((decisions) => {
    const first = decisions[0]
    const isAttack = ATTACK_TOOLS.has(first.tool_name)
    const hasTenuoDeny = decisions.some((d) => d.layer === 'tenuo' && d.decision === 'deny')
    const allStandardAllow = decisions
      .filter((d) => d.layer !== 'tenuo')
      .every((d) => d.decision === 'allow')
    return { decisions, isAttack, hasTenuoDeny, allStandardAllow }
  })

  // Sort: Tenuo denials first, then attacks, then rest
  calls.sort((a, b) => {
    if (a.hasTenuoDeny && !b.hasTenuoDeny) return -1
    if (!a.hasTenuoDeny && b.hasTenuoDeny) return 1
    if (a.isAttack && !b.isAttack) return -1
    if (!a.isAttack && b.isAttack) return 1
    return 0
  })

  return calls.slice(0, 12)
}

export function AuthDecisionPanel() {
  const [records, setRecords] = useState<AuthRecord[]>([])

  useEffect(() => {
    const poll = async () => {
      try {
        setRecords(await fetchAuthDecisions())
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  const sections = buildSections(records)
  const hasTenuo = records.some((r) => r.layer === 'tenuo')

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
          Authorization Decisions
        </h2>
        {records.length > 0 && (
          <span className="text-[10px] text-gray-600">
            {records.length} checks across {sections.length} tool calls
          </span>
        )}
      </div>

      {/* Legend */}
      {records.length > 0 && (
        <div className="flex gap-3 mb-3 text-[10px]">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500" /> ALLOW
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-500" /> DENY
          </span>
          {hasTenuo && (
            <span className="text-green-400">
              Tenuo = 5th layer (warrant enforcement)
            </span>
          )}
        </div>
      )}

      <div className="space-y-2">
        {sections.map(({ decisions, isAttack, hasTenuoDeny, allStandardAllow }) => {
          const first = decisions[0]
          const isBankViolation = decisions.some(
            (d) => d.layer === 'tenuo' && d.reason?.includes('bank_account')
          )

          return (
            <div
              key={first.request_id}
              className={`rounded border overflow-hidden ${
                hasTenuoDeny
                  ? 'border-red-700 bg-red-950/30'
                  : isAttack
                    ? 'border-yellow-800 bg-yellow-950/20'
                    : 'border-gray-800 bg-gray-900'
              }`}
            >
              {/* Tool call header */}
              <div className={`px-3 py-2 flex items-center justify-between ${
                hasTenuoDeny ? 'bg-red-950/50' : ''
              }`}>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">{first.agent_id}</span>
                  <span className="text-gray-700">→</span>
                  <span className={`text-xs font-medium ${
                    hasTenuoDeny ? 'text-red-400' : isAttack ? 'text-yellow-400' : 'text-blue-400'
                  }`}>
                    {first.tool_name}
                  </span>
                </div>
                {hasTenuoDeny && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300 font-medium">
                    BLOCKED
                  </span>
                )}
                {!hasTenuoDeny && allStandardAllow && !hasTenuo && isAttack && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">
                    ALL APPROVED
                  </span>
                )}
              </div>

              {/* Auth layers as compact row */}
              <div className="px-3 pb-2 flex gap-1.5">
                {LAYER_ORDER.map((layer) => {
                  const d = decisions.find((r) => r.layer === layer)
                  if (!d) return null
                  const isAllow = d.decision === 'allow'
                  const isTenuo = layer === 'tenuo'

                  return (
                    <div
                      key={layer}
                      className={`flex-1 px-1.5 py-1 rounded text-[10px] text-center ${
                        isAllow
                          ? isTenuo
                            ? 'bg-green-900/40 text-green-400'
                            : hasTenuoDeny
                              ? 'bg-green-900/50 text-green-400 border border-green-800/50'
                              : 'bg-green-900/20 text-green-600'
                          : isTenuo
                            ? 'bg-red-900/60 text-red-300 border border-red-700 font-medium'
                            : 'bg-red-900/40 text-red-400'
                      }`}
                      title={d.reason}
                    >
                      <div className="font-medium">{LAYER_LABELS[layer]}</div>
                      <div className="text-lg leading-none my-0.5">
                        {isAllow ? '✓' : '✗'}
                      </div>
                      <div className="text-gray-600">{d.latency_us}μs</div>
                    </div>
                  )
                })}
              </div>

              {/* Show violation reason for Tenuo denials */}
              {hasTenuoDeny && (
                <div className="px-3 pb-2">
                  <div className="text-[10px] text-red-400 bg-red-950/50 rounded px-2 py-1">
                    {isBankViolation
                      ? 'bank_account: expected legitimate account, got attacker account — DENIED'
                      : decisions.find((d) => d.layer === 'tenuo' && d.decision === 'deny')?.reason || 'Warrant violation'
                    }
                  </div>
                </div>
              )}
            </div>
          )
        })}
        {sections.length === 0 && (
          <div className="text-gray-600 text-sm text-center py-4">
            Authorization decisions will appear here when you process a batch.
          </div>
        )}
      </div>
    </div>
  )
}
