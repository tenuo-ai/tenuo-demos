/**
 * Authorization decisions as a table — one row per tool call, one column per auth layer.
 *
 * The presenter glances at this and says:
 * "Every standard auth layer says yes. Tenuo says no."
 */
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

const LAYERS = ['gcp_sa', 'oauth', 'spicedb', 'opa', 'tenuo']
const LAYER_LABELS: Record<string, string> = {
  gcp_sa: 'GCP SA',
  oauth: 'OAuth',
  spicedb: 'SpiceDB',
  opa: 'OPA',
  tenuo: 'Tenuo',
}

const ATTACK_TOOLS = new Set(['update_vendor_bank', 'initiate_payment'])

interface ToolCall {
  requestId: string
  agent: string
  tool: string
  layers: Record<string, { decision: string; reason: string; latency: number }>
}

function buildTable(records: AuthRecord[]): ToolCall[] {
  const byRequest: Record<string, AuthRecord[]> = {}
  for (const r of records) {
    if (!byRequest[r.request_id]) byRequest[r.request_id] = []
    byRequest[r.request_id].push(r)
  }

  return Object.entries(byRequest).map(([requestId, recs]) => ({
    requestId,
    agent: recs[0].agent_id,
    tool: recs[0].tool_name,
    layers: Object.fromEntries(
      recs.map((r) => [r.layer, { decision: r.decision, reason: r.reason, latency: r.latency_us }])
    ),
  }))
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

  const rows = buildTable(records)
  const hasTenuo = records.some((r) => r.layer === 'tenuo')
  const visibleLayers = hasTenuo ? LAYERS : LAYERS.filter((l) => l !== 'tenuo')

  if (rows.length === 0) {
    return (
      <div className="p-4">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
          Authorization Decisions
        </h2>
        <div className="text-gray-600 text-sm text-center py-4">
          Decisions will appear here when you process a batch.
        </div>
      </div>
    )
  }

  // Sort: Tenuo denials first, then attack tools, then rest
  const sorted = [...rows].sort((a, b) => {
    const aDeny = a.layers.tenuo?.decision === 'deny'
    const bDeny = b.layers.tenuo?.decision === 'deny'
    if (aDeny && !bDeny) return -1
    if (!aDeny && bDeny) return 1
    const aAttack = ATTACK_TOOLS.has(a.tool)
    const bAttack = ATTACK_TOOLS.has(b.tool)
    if (aAttack && !bAttack) return -1
    if (!aAttack && bAttack) return 1
    return 0
  })

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
        Authorization Decisions
      </h2>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="py-2 text-left text-gray-500 font-medium w-48">Tool Call</th>
              {visibleLayers.map((layer) => (
                <th
                  key={layer}
                  className={`py-2 text-center font-medium w-16 ${
                    layer === 'tenuo' ? 'text-green-400' : 'text-gray-500'
                  }`}
                >
                  {LAYER_LABELS[layer]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const isAttack = ATTACK_TOOLS.has(row.tool)
              const tenuoDeny = row.layers.tenuo?.decision === 'deny'
              const allStandardAllow = LAYERS
                .filter((l) => l !== 'tenuo')
                .every((l) => !row.layers[l] || row.layers[l].decision === 'allow')

              return (
                <tr
                  key={row.requestId}
                  className={`border-b ${
                    tenuoDeny
                      ? 'border-red-900 bg-red-950/30'
                      : isAttack && allStandardAllow
                        ? 'border-yellow-900/50 bg-yellow-950/10'
                        : 'border-gray-900'
                  }`}
                >
                  {/* Tool name */}
                  <td className="py-2 pr-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-gray-600 text-[10px]">{row.agent.split('-')[0]}</span>
                      <span className={`font-medium ${
                        tenuoDeny ? 'text-red-400' : isAttack ? 'text-yellow-400' : 'text-gray-300'
                      }`}>
                        {row.tool}
                      </span>
                      {tenuoDeny && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-red-900 text-red-300">
                          BLOCKED
                        </span>
                      )}
                    </div>
                    {tenuoDeny && row.layers.tenuo?.reason && (
                      <div className="text-[10px] text-red-400/70 mt-0.5 pl-1">
                        {row.layers.tenuo.reason.includes('bank_account')
                          ? 'bank_account mismatch — warrant pinned to legitimate account'
                          : row.layers.tenuo.reason.includes('not authorize')
                            ? 'tool not in warrant capabilities'
                            : row.layers.tenuo.reason
                        }
                      </div>
                    )}
                  </td>

                  {/* Auth layers */}
                  {visibleLayers.map((layer) => {
                    const d = row.layers[layer]
                    if (!d) return <td key={layer} className="py-2 text-center text-gray-800">—</td>

                    const isAllow = d.decision === 'allow'
                    const isTenuo = layer === 'tenuo'

                    return (
                      <td
                        key={layer}
                        className="py-2 text-center"
                        title={d.reason}
                      >
                        <span className={`text-base ${
                          isAllow
                            ? isTenuo
                              ? 'text-green-400'
                              : tenuoDeny
                                ? 'text-green-500'  // Bright green when standard approves but Tenuo denies
                                : 'text-green-700'
                            : isTenuo
                              ? 'text-red-400 font-bold'
                              : 'text-red-500'
                        }`}>
                          {isAllow ? '✓' : '✗'}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      <div className="mt-3 text-[10px] text-gray-600">
        {rows.length} tool calls · {visibleLayers.length} auth layers
        {hasTenuo && (() => {
          const denied = rows.filter((r) => r.layers.tenuo?.decision === 'deny').length
          const allowed = rows.filter((r) => r.layers.tenuo?.decision === 'allow').length
          return ` · Tenuo: ${allowed} allowed, ${denied} blocked`
        })()}
      </div>
    </div>
  )
}
