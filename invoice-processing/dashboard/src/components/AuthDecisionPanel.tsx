/**
 * Authorization decisions grouped by invoice.
 *
 * Each invoice is a collapsible section showing:
 * - Invoice header (ID, vendor, amount)
 * - Invoice details (description, notes — click to expand)
 * - Auth decision table (one row per tool call, one column per auth layer)
 */
import { useEffect, useState } from 'react'
import { fetchInvoiceAuthSummary, fetchWarrantInfo } from '../lib/api'

const LAYERS = ['gcp_sa', 'oauth', 'spicedb', 'opa', 'tenuo']
const LAYER_LABELS: Record<string, string> = {
  gcp_sa: 'GCP SA',
  oauth: 'OAuth',
  spicedb: 'SpiceDB',
  opa: 'OPA',
  tenuo: 'Tenuo',
}

// Static tool lists for attenuated sub-warrants.
// Derived from attenuate_for_invoice_processor_cloud() and attenuate_for_payment_executor_cloud().
const INVOICE_PROCESSOR_TOOLS = new Set([
  'read_invoice', 'read_po', 'lookup_vendor', 'verify_vendor', 'approve_invoice',
])
const PAYMENT_EXECUTOR_TOOLS = new Set([
  'lookup_vendor', 'initiate_payment', 'approve_payment', 'get_fx_rate',
])
const PAYMENT_PINNED_TOOLS = new Set(['initiate_payment'])

interface WarrantTool {
  name: string
  constraints: Record<string, string>
}

function WarrantChain({ tools }: { tools: WarrantTool[] }) {
  const [open, setOpen] = useState(false)

  const sortedTools = [...tools].sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="mb-3">
      {/* Always-visible delegation rail */}
      <div className="flex items-center gap-1.5 text-[11px] flex-wrap">
        <span className="text-yellow-600">🔑</span>
        <span className="text-gray-500">Root</span>
        <span className="text-gray-700 mx-0.5">→</span>
        <span className="text-blue-400 font-medium">Invoice Proc</span>
        <span className="font-mono px-1.5 py-0.5 rounded bg-red-950/50 text-red-400 text-[10px]">
          − update_vendor_bank
        </span>
        <span className="text-gray-700 mx-0.5">→</span>
        <span className="text-purple-400 font-medium">Payment Exec</span>
        <span className="font-mono px-1.5 py-0.5 rounded bg-purple-950/50 text-purple-400 text-[10px]">
          bank_account 🔒
        </span>
        <button
          onClick={() => setOpen(!open)}
          className="ml-1 text-gray-700 hover:text-gray-400 transition-colors"
          title="Show full warrant table"
        >
          {open ? '▾' : '▸'}
        </button>
      </div>

      {open && (
        <div className="mt-2 rounded border border-gray-800 bg-gray-900/60 overflow-hidden">
          <div className="px-3 pt-2 pb-1 text-[9px] text-gray-600 border-b border-gray-800">
            Issued by Finance Controller before delegation — cannot be widened by any agent
          </div>
          {/* Column headers */}
          <div className="grid grid-cols-[1fr_auto_auto_auto] text-[9px] uppercase tracking-wider text-gray-600 border-b border-gray-800 px-3 py-1.5">
            <span>Tool</span>
            <span className="w-20 text-center text-gray-500">Root</span>
            <span className="w-24 text-center text-blue-700">Invoice Proc</span>
            <span className="w-24 text-center text-purple-700">Payment Exec</span>
          </div>

          <div className="max-h-56 overflow-y-auto">
            {sortedTools.map((t) => {
              const inInvoice = INVOICE_PROCESSOR_TOOLS.has(t.name)
              const inPayment = PAYMENT_EXECUTOR_TOOLS.has(t.name)
              const isPinned = PAYMENT_PINNED_TOOLS.has(t.name)
              const isRemovedFromInvoice = !inInvoice
              const isAttackTool = t.name === 'update_vendor_bank'
              return (
                <div
                  key={t.name}
                  className={`grid grid-cols-[1fr_auto_auto_auto] items-center px-3 py-0.5 text-[11px] border-b border-gray-800/50 last:border-0 ${
                    isAttackTool ? 'bg-red-950/20' : ''
                  }`}
                >
                  <span className={`font-mono ${isAttackTool ? 'text-red-400' : 'text-gray-400'}`}>
                    {t.name}
                    {isAttackTool && (
                      <span className="ml-1 text-[9px] text-red-600">← attack vector</span>
                    )}
                  </span>
                  {/* Root */}
                  <span className="w-20 text-center text-green-700">✓</span>
                  {/* Invoice Processor */}
                  <span className={`w-24 text-center ${
                    inInvoice
                      ? 'text-blue-600'
                      : isAttackTool
                        ? 'text-red-500 font-bold'
                        : 'text-gray-700'
                  }`}>
                    {inInvoice ? '✓' : isRemovedFromInvoice ? (isAttackTool ? '✗ removed' : '—') : '—'}
                  </span>
                  {/* Payment Executor */}
                  <span className={`w-24 text-center ${inPayment ? 'text-purple-500' : 'text-gray-700'}`}>
                    {inPayment
                      ? isPinned
                        ? <span>✓ <span className="text-[9px] text-purple-700">🔒 pinned</span></span>
                        : '✓'
                      : '—'}
                  </span>
                </div>
              )
            })}
          </div>

          <div className="px-3 py-1.5 text-[9px] text-gray-700 border-t border-gray-800 flex gap-3">
            <span><span className="text-blue-700">Invoice Proc</span> = root minus <span className="text-red-600">update_vendor_bank</span></span>
            <span>·</span>
            <span><span className="text-purple-700">Payment Exec</span> = payment tools, bank details <span className="text-purple-700">🔒 pinned</span> from vendor master</span>
          </div>
        </div>
      )}
    </div>
  )
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

export function AuthDecisionPanel({ tenuoActive = false }: { tenuoActive?: boolean }) {
  const [summaries, setSummaries] = useState<InvoiceSummary[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [warrantTools, setWarrantTools] = useState<WarrantTool[]>([])

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

  // Fetch warrant info once (it doesn't change between polls)
  useEffect(() => {
    fetchWarrantInfo()
      .then((info) => { if (info.warrant?.tools) setWarrantTools(info.warrant.tools) })
      .catch(() => {})
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
        {tenuoActive && warrantTools.length > 0 && <WarrantChain tools={warrantTools} />}
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

      {/* Warrant chain — visible only in Act 3 / Tenuo mode */}
      {tenuoActive && warrantTools.length > 0 && (
        <WarrantChain tools={warrantTools} />
      )}

      <div className="space-y-4">
        {summaries.filter((s) => s.tool_calls.length > 0).map((summary) => {
          const inv = summary.invoice
          const isExpanded = expanded === inv.id
          // Only mark as attack if update_vendor_bank was called for THIS invoice.
          // For the synthetic simulation entry, invoice_id on the tool call is null — match by inv.id.
          const isSimulation = inv.id === 'simulation'
          const hasAttack = summary.tool_calls.some(
            (tc) => tc.tool_name === 'update_vendor_bank' &&
              (isSimulation ? tc.invoice_id === null : tc.invoice_id === inv.id)
          )
          const hasTenuoDeny = summary.tool_calls.some(
            (tc) => tc.layers.tenuo?.decision === 'deny' &&
              (isSimulation ? tc.invoice_id === null : tc.invoice_id === inv.id)
          )
          // Only show bank poisoned if this invoice's vendor was the target
          const bankPoisoned = inv.bank_account === ATTACKER_ACCOUNT && inv.vendor_id === 'V-4521'

          return (
            <div
              key={inv.id}
              className={`rounded-lg border overflow-hidden ${
                isSimulation
                  ? 'border-orange-800 bg-orange-950/10'
                  : hasTenuoDeny
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
                    <span className={`text-sm font-medium ${isSimulation ? 'text-orange-300' : 'text-gray-200'}`}>
                      {isSimulation ? '⚡ Simulated Attack' : inv.id}
                    </span>
                    {!isSimulation && <span className="text-xs text-gray-500">{inv.vendor_name}</span>}
                    {inv.amount != null && (
                      <span className="text-xs text-gray-400">
                        ${inv.amount?.toLocaleString()} {inv.currency}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {isSimulation && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/60 text-orange-300">
                        LLM BYPASSED — DIRECT CALL
                      </span>
                    )}
                    {!isSimulation && hasAttack && !hasTenuoDeny && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300">
                        4/4 ALLOWED · authorization gap
                      </span>
                    )}
                    {!isSimulation && hasTenuoDeny && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">
                        BLOCKED · not in task delegation
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
                          const isAttackTool = tc.tool_name === 'update_vendor_bank'

                          return (
                            <tr
                              key={tc.request_id}
                              className={`border-b ${
                                tenuoDeny
                                  ? 'border-red-900/50 bg-red-950/20'
                                  : isAttackTool
                                    ? 'border-yellow-900/30 bg-yellow-950/10'
                                    : 'border-gray-900/50'
                              }`}
                            >
                              <td className="py-1.5">
                                <span className={`${
                                  tenuoDeny ? 'text-red-400' : isAttackTool ? 'text-yellow-400' : 'text-gray-300'
                                }`}>
                                  {tc.tool_name}
                                </span>
                                {isAttackTool && !tenuoDeny && !isSimulation && (
                                  <div className="text-[9px] text-yellow-600/80 mt-0.5">
                                    correctly authorized · no task scope in standard auth
                                  </div>
                                )}
                                {tenuoDeny && (
                                  <div className="text-[9px] text-red-400/70 mt-0.5">
                                    {tc.layers.tenuo?.reason?.includes('not authorize')
                                      ? 'not in task delegation'
                                      : tc.layers.tenuo?.reason?.includes('bank_account')
                                        ? 'bank account pinned at delegation time'
                                        : 'denied'
                                    }
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
                                    <span className={`${
                                      isAllow
                                        ? tenuoDeny && !isTenuo
                                          ? 'text-green-500'
                                          : isTenuo
                                            ? 'text-green-400'
                                            : 'text-green-700'
                                        : isTenuo
                                          ? 'text-red-400 font-bold text-base'
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
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
