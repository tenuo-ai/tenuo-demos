/**
 * Warrant inspector: the decoded warrants minted in the current Act 3 run.
 *
 * Shows the Finance Controller's root warrant and the child warrants it
 * attenuated for the selected invoice, field by field, so the presenter can
 * point at what each agent was actually handed: the Invoice Processor's
 * warrant has no update_vendor_bank, and the Payment Executor's pins
 * bank_account with Exact(...). Each child's issuer is its parent's holder.
 */
import { useEffect, useState } from 'react'

interface DecodedWarrant {
  id?: string
  type?: string
  depth?: number
  max_depth?: number
  issuer?: string | null
  holder?: string | null
  parent_hash?: string | null
  expires_at?: string
  ttl_seconds?: number
  tools?: Record<string, Record<string, string>>
  token?: string
  error?: string
}

interface MintedWarrant {
  holder_agent: string
  invoice_id: string | null
  warrant: DecodedWarrant
  minted_at: string
}

const AGENT_LABELS: Record<string, string> = {
  'finance-controller': 'Finance Controller',
  'invoice-processor': 'Invoice Processor',
  'payment-executor': 'Payment Executor',
}

const FIELD_ORDER: (keyof DecodedWarrant)[] = [
  'id', 'type', 'depth', 'max_depth', 'issuer', 'holder', 'parent_hash',
  'expires_at', 'ttl_seconds', 'tools', 'token', 'error',
]

const sortKeys = <T,>(obj: Record<string, T>): Record<string, T> =>
  Object.fromEntries(Object.entries(obj).sort(([a], [b]) => a.localeCompare(b)))

// Fixed field order (the database doesn't keep it), sorted tools and
// arguments, and a shortened token; the full token is copyable.
function displayJson(w: DecodedWarrant): string {
  const shown: Record<string, unknown> = {}
  for (const key of FIELD_ORDER) {
    if (!(key in w)) continue
    let value: unknown = w[key]
    if (key === 'tools' && w.tools) {
      value = Object.fromEntries(
        Object.entries(sortKeys(w.tools)).map(([tool, args]) => [tool, sortKeys(args)]),
      )
    }
    if (key === 'token' && w.token && w.token.length > 48) {
      value = `${w.token.slice(0, 48)}… (${w.token.length} chars)`
    }
    shown[key] = value
  }
  return JSON.stringify(shown, null, 2)
}

function lineClass(line: string): string {
  if (line.includes('Exact(')) return 'text-amber-300'
  if (/"(issuer|holder|parent_hash)"/.test(line)) return 'text-sky-300'
  return 'text-gray-300'
}

function WarrantCard({ minted }: { minted: MintedWarrant }) {
  const [copied, setCopied] = useState(false)
  const w = minted.warrant
  const isRoot = !minted.invoice_id
  const agent = AGENT_LABELS[minted.holder_agent] ?? minted.holder_agent

  const copyToken = async () => {
    if (!w.token) return
    try {
      await navigator.clipboard.writeText(w.token)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable; nothing to do
    }
  }

  return (
    <div className="rounded border border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <div className="text-xs">
          <span className={isRoot ? 'text-blue-400' : 'text-green-400'}>
            {isRoot ? 'Root warrant' : 'Attenuated warrant'}
          </span>
          <span className="text-gray-500"> · held by </span>
          <span className="text-gray-200">{agent}</span>
          {w.depth !== undefined && <span className="text-gray-600"> · depth {w.depth}</span>}
        </div>
        {w.token && (
          <button
            onClick={copyToken}
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
          >
            {copied ? 'Copied' : 'Copy token'}
          </button>
        )}
      </div>
      <pre className="px-3 py-2 text-[11px] leading-relaxed font-mono overflow-x-auto">
        {displayJson(w).split('\n').map((line, i) => (
          <div key={i} className={lineClass(line)}>{line}</div>
        ))}
      </pre>
    </div>
  )
}

export function WarrantInspector({ invoiceId }: { invoiceId: string }) {
  const [warrants, setWarrants] = useState<MintedWarrant[]>([])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`/api/warrants?invoice_id=${encodeURIComponent(invoiceId)}`)
        const data = await res.json()
        if (!cancelled) setWarrants(Array.isArray(data) ? data : [])
      } catch {
        // ignore; next poll retries
      }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [invoiceId])

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
          Warrant inspector
        </h2>
        <span className="text-xs text-gray-500">{invoiceId}</span>
      </div>
      {warrants.length === 0 ? (
        <div className="text-xs text-gray-600">
          Warrants appear here as the Finance Controller mints them for this invoice.
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-[11px] text-gray-500">
            Each attenuated warrant is signed by its parent's holder: its <span className="text-sky-300">issuer</span> is
            the root's <span className="text-sky-300">holder</span>, and <span className="text-sky-300">parent_hash</span> binds
            it to that root. <span className="text-amber-300">Exact(…)</span> pins an argument to one value.
          </div>
          {warrants.map((m) => (
            <WarrantCard key={m.warrant.id ?? m.minted_at} minted={m} />
          ))}
        </div>
      )}
    </div>
  )
}
