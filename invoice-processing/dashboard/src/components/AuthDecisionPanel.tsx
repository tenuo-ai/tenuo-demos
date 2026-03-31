/**
 * Authorization decisions grouped by invoice.
 *
 * Each invoice is a collapsible section showing:
 * - Invoice header (ID, vendor, amount)
 * - Invoice details (description, notes — click to expand)
 * - Auth decision table (one row per tool call, one column per auth layer)
 */
import { useEffect, useState } from 'react'
import { fetchInvoiceAuthSummary } from '../lib/api'

const LAYERS = ['gcp_sa', 'oauth', 'spicedb', 'opa', 'tenuo']
const LAYER_LABELS: Record<string, string> = {
  gcp_sa: 'GCP SA',
  oauth: 'OAuth',
  spicedb: 'SpiceDB',
  opa: 'OPA',
  tenuo: 'Tenuo',
}

interface LayerDecision {
  decision: string
  reason: string
  latency_us: number
}

interface ToolCall {
  request_id: string
  agent_id: string
  tool_name: string
  invoice_id: string | null
  layers: Record<string, LayerDecision>
}

interface InvoiceInfo {
  id: string
  vendor_id?: string
  vendor_name?: string
  amount?: number
  currency?: string
  description?: string
  status?: string
  notes?: string
  bank_account?: string
  bank_routing?: string
}

interface InvoiceSummary {
  invoice: InvoiceInfo
  tool_calls: ToolCall[]
}

const ATTACKER_ACCOUNT = '8847291034'

function getDenyReason(reason: string | undefined): string {
  if (reason?.includes('not authorize')) return 'tool not in warrant'
  if (reason?.includes('bank_account')) return 'bank_account mismatch'
  return reason || 'denied'
}

function getDecisionColor(isAllow: boolean, isGenuineDeny: boolean, isTenuo: boolean): string {
  if (isAllow) {
    if (isGenuineDeny && !isTenuo) return 'text-green-500'
    if (isTenuo) return 'text-green-400'
    return 'text-green-700'
  }
  if (isTenuo) return 'text-red-400 font-bold text-base'
  return 'text-red-500'
}

export function AuthDecisionPanel() {
  const [summaries, setSummaries] = useState<InvoiceSummary[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    const poll = async () => {
      try {
        setSummaries(await fetchInvoiceAuthSummary())
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  const hasTenuo = summaries.some((s) =>
    s.tool_calls.some((tc) => tc.layers.tenuo)
  )
  const visibleLayers = hasTenuo ? LAYERS : LAYERS.filter((l) => l !== 'tenuo')

  if (summaries.length === 0) {
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

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
        Authorization Decisions
      </h2>

      <div className="space-y-4">
        {summaries.filter((s) => s.tool_calls.length > 0).map((summary) => {
          const inv = summary.invoice
          const isExpanded = expanded === inv.id
          // Only mark as attack if update_vendor_bank was attempted on THIS invoice
          const hasAttack = summary.tool_calls.some(
            (tc) => tc.tool_name === 'update_vendor_bank'
          )
          // Only show "blocked by Tenuo" for actual attack tool denials
          // (update_vendor_bank denied or bank_account constraint violation)
          const hasTenuoDeny = summary.tool_calls.some(
            (tc) => tc.layers.tenuo?.decision === 'deny' && (
              tc.tool_name === 'update_vendor_bank' ||
              (tc.layers.tenuo?.reason || '').includes('bank_account')
            )
          )
          const bankPoisoned = inv.bank_account === ATTACKER_ACCOUNT && inv.vendor_id === 'V-4521'

          return (
            <div
              key={inv.id}
              className={`rounded-lg border overflow-hidden ${
                hasTenuoDeny
                  ? 'border-green-800 bg-green-950/10'
                  : hasAttack
                    ? 'border-red-800 bg-red-950/10'
                    : 'border-gray-800 bg-gray-900/50'
              }`}
            >
              {/* Invoice header — click to expand */}
              <button
                onClick={() => setExpanded(isExpanded ? null : inv.id)}
                className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-800/30 transition-colors"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-200">{inv.id}</span>
                    <span className="text-xs text-gray-500">{inv.vendor_name}</span>
                    {inv.amount ? (
                      <span className="text-xs text-gray-400">
                        ${inv.amount?.toLocaleString()} {inv.currency}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {hasAttack && !hasTenuoDeny && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300">
                        ATTACK SUCCEEDED
                      </span>
                    )}
                    {hasTenuoDeny && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">
                        ATTACK BLOCKED BY TENUO
                      </span>
                    )}
                    {bankPoisoned && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/50 text-red-400">
                        Bank changed to attacker
                      </span>
                    )}
                    <span className="text-[10px] text-gray-600">
                      {summary.tool_calls.length} tool calls
                    </span>
                  </div>
                </div>
                <span className="text-gray-600 text-xs">{isExpanded ? '▾' : '▸'}</span>
              </button>

              {/* Expanded: invoice details + auth table */}
              {isExpanded && (
                <div className="border-t border-gray-800">
                  {/* Invoice details */}
                  {inv.description && (
                    <div className="px-4 py-2 bg-gray-900/50 text-xs">
                      <div className="text-gray-500">{inv.description}</div>
                      {inv.notes && (
                        <div className={`mt-2 p-2 rounded border font-mono whitespace-pre-wrap text-[10px] ${
                          hasAttack
                            ? 'bg-red-950/30 border-red-800 text-red-300'
                            : 'bg-gray-800 border-gray-700 text-gray-400'
                        }`}>
                          <div className="text-[9px] text-gray-600 mb-1">Notes field:</div>
                          {inv.notes}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Auth decisions table */}
                  <div className="px-4 py-2">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-800">
                          <th className="py-1.5 text-left text-gray-500 font-medium">Tool</th>
                          {visibleLayers.map((layer) => (
                            <th
                              key={layer}
                              className={`py-1.5 text-center font-medium w-14 ${
                                layer === 'tenuo' ? 'text-green-400' : 'text-gray-500'
                              }`}
                            >
                              {LAYER_LABELS[layer]}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {summary.tool_calls.map((tc) => {
                          const tenuoDeny = tc.layers.tenuo?.decision === 'deny'
                          // Only highlight as attack if it's genuinely an attack tool or bank violation
                          const isGenuineDeny = tenuoDeny && (
                            tc.tool_name === 'update_vendor_bank' ||
                            (tc.layers.tenuo?.reason || '').includes('bank_account') ||
                            (tc.layers.tenuo?.reason || '').includes('not authorize')
                          )
                          const isAttackTool = tc.tool_name === 'update_vendor_bank'

                          return (
                            <tr
                              key={tc.request_id}
                              className={`border-b ${
                                isGenuineDeny
                                  ? 'border-red-900/50 bg-red-950/20'
                                  : isAttackTool
                                    ? 'border-yellow-900/30 bg-yellow-950/10'
                                    : 'border-gray-900/50'
                              }`}
                            >
                              <td className="py-1.5">
                                <span className={`${
                                  isGenuineDeny ? 'text-red-400' : isAttackTool ? 'text-yellow-400' : 'text-gray-300'
                                }`}>
                                  {tc.tool_name}
                                </span>
                                {isGenuineDeny && (
                                  <div className="text-[9px] text-red-400/70 mt-0.5">
                                    {getDenyReason(tc.layers.tenuo?.reason)}
                                  </div>
                                )}
                              </td>
                              {visibleLayers.map((layer) => {
                                const d = tc.layers[layer]
                                if (!d) return <td key={layer} className="text-center text-gray-800">—</td>
                                const isAllow = d.decision === 'allow'
                                const isTenuo = layer === 'tenuo'
                                return (
                                  <td key={layer} className="py-1.5 text-center" title={d.reason}>
                                    <span className={getDecisionColor(isAllow, isGenuineDeny, isTenuo)}>
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
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
