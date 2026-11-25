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

interface CardProps {
  minted: MintedWarrant
  // The run's root warrant, to work out which tools a child lost.
  root?: DecodedWarrant
  // Every warrant shown, to name the agent behind a signing key.
  all: MintedWarrant[]
  open: boolean
  onToggle: () => void
  // Child warrant cards, shown nested when this card is open.
  children?: React.ReactNode
}

function WarrantCard({ minted, root, all, open, onToggle, children }: CardProps) {
  const [copied, setCopied] = useState(false)
  const [raw, setRaw] = useState(false)
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

  const tools = Object.keys(w.tools ?? {}).sort()
  const removed = root && !isRoot
    ? Object.keys(root.tools ?? {}).filter((t) => !(t in (w.tools ?? {}))).sort()
    : []
  const pins: { arg: string; value: string; exact: boolean }[] = []
  for (const [tool, args] of Object.entries(w.tools ?? {})) {
    for (const [arg, constraint] of Object.entries(args)) {
      const value = constraintValue(constraint)
      pins.push({ arg: `${tool}.${arg}`, value, exact: constraint.startsWith('Exact(') })
    }
  }
  pins.sort((a, b) => Number(b.exact) - Number(a.exact) || a.arg.localeCompare(b.arg))
  const issuerAgent = holderAgent(w.issuer, all)
  const pinned = pins.filter((p) => p.exact).length
  const hint = [
    `${tools.length} tools`,
    pinned > 0 ? `${pinned} pinned` : null,
    removed.includes('update_vendor_bank') ? 'no update_vendor_bank' : null,
    formatTtl(w.ttl_seconds),
  ].filter(Boolean).join(' · ')

  return (
    <div className="rounded border border-gray-800 bg-gray-900">
      <div className={`flex items-center justify-between gap-2 px-3 py-2 ${open ? 'border-b border-gray-800' : ''}`}>
        <button
          onClick={onToggle}
          aria-expanded={open}
          className="flex-1 min-w-0 text-left text-xs hover:opacity-80"
        >
          <span className="text-gray-500 inline-block w-3">{open ? '▾' : '▸'}</span>
          <span className={isRoot ? 'text-blue-400' : 'text-green-400'}>
            {isRoot ? 'Root warrant' : 'Attenuated warrant'}
          </span>
          <span className="text-gray-500"> · held by </span>
          <span className="text-gray-200">{agent}</span>
          {!open && <span className="text-gray-600"> · {hint}</span>}
        </button>
        {open && (
          <div className="flex gap-1 shrink-0">
            <button
              onClick={() => setRaw(!raw)}
              className="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
            >
              {raw ? 'Summary' : 'Raw'}
            </button>
            {w.token && (
              <button
                onClick={copyToken}
                className="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
              >
                {copied ? 'Copied' : 'Copy token'}
              </button>
            )}
          </div>
        )}
      </div>

      {open && (raw ? (
        <pre className="px-3 py-2 text-[12px] leading-relaxed font-mono overflow-x-auto">
          {displayJson(w).split('\n').map((line, i) => (
            <div key={i} className={lineClass(line)}>{line}</div>
          ))}
        </pre>
      ) : (
        <dl className="px-3 py-2 grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-1.5 text-xs">
          <Row label="Held by">
            {agent} <Key hex={w.holder} />
          </Row>
          <Row label="Signed by">
            {isRoot ? 'Trusted issuer' : issuerAgent ?? 'Unknown key'} <Key hex={w.issuer} />
          </Row>
          {!isRoot && (
            <Row label="Delegated from">
              Root warrant <span className="text-gray-500 font-mono">parent_hash {short(w.parent_hash)}</span>
            </Row>
          )}
          <Row label="Valid for">
            {formatTtl(w.ttl_seconds)}
            {w.expires_at && <span className="text-gray-500"> · expires {formatTime(w.expires_at)}</span>}
          </Row>
          <Row label="Allowed tools">
            <span className="text-gray-400">{tools.length}:</span> {tools.join(', ')}
          </Row>
          {!isRoot && (
            <Row label="Removed">
              {removed.length === 0 ? (
                <span className="text-gray-500">none</span>
              ) : (
                removed.map((t, i) => (
                  <span key={t} className={t === 'update_vendor_bank' ? 'text-red-400 font-medium' : 'text-gray-500'}>
                    {t}{i < removed.length - 1 ? ', ' : ''}
                  </span>
                ))
              )}
            </Row>
          )}
          <Row label="Argument limits">
            {pins.length === 0 ? (
              <span className="text-gray-500">none: any arguments</span>
            ) : (
              <div className="space-y-0.5 font-mono">
                {pins.map((p) => (
                  <div key={p.arg}>
                    <span className="text-gray-400">{p.arg}</span>{' '}
                    <span className={p.exact ? 'text-amber-300' : 'text-gray-500'}>{p.value}</span>
                  </div>
                ))}
              </div>
            )}
          </Row>
          <Row label="Warrant ID">
            <span className="font-mono text-gray-500">{w.id}</span>
          </Row>
        </dl>
      ))}

      {/* Warrants delegated from this one, nested so the cascade is visible */}
      {open && children && (
        <div className="ml-4 mr-2 mb-2 pl-3 border-l border-gray-700 space-y-2">
          <div className="eyebrow text-[11px] text-gray-500 pt-1">Delegated to</div>
          {children}
        </div>
      )}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-200 min-w-0 break-words">{children}</dd>
    </>
  )
}

function Key({ hex }: { hex?: string | null }) {
  if (!hex) return null
  return <span className="text-sky-300/80 font-mono"> key {short(hex)}</span>
}

const short = (hex?: string | null) => (hex ? `${hex.slice(0, 8)}…` : '—')

// Exact('x') -> "= x", Wildcard() -> "any value"; other types shown as-is.
function constraintValue(constraint: string): string {
  const exact = constraint.match(/^Exact\((['"])(.*)\1\)$/)
  if (exact) return `= ${exact[2]}`
  if (constraint === 'Wildcard()') return 'any value'
  return constraint
}

function holderAgent(key: string | null | undefined, all: MintedWarrant[]): string | undefined {
  const match = all.find((m) => key && m.warrant.holder === key)
  return match ? AGENT_LABELS[match.holder_agent] ?? match.holder_agent : undefined
}

function formatTtl(seconds?: number): string {
  if (!seconds) return '—'
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function WarrantInspector({ invoiceId }: { invoiceId: string }) {
  const [warrants, setWarrants] = useState<MintedWarrant[]>([])
  const [panelOpen, setPanelOpen] = useState(true)
  // Open/closed per warrant id. Unset means the default: root open, children closed.
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({})

  const rootEntry = warrants.find((m) => !m.invoice_id)
  const childEntries = warrants.filter((m) => m.invoice_id)
  const idOf = (m: MintedWarrant) => m.warrant.id ?? m.minted_at
  const isOpen = (m: MintedWarrant) => openIds[idOf(m)] ?? !m.invoice_id
  const toggle = (m: MintedWarrant) => setOpenIds((s) => ({ ...s, [idOf(m)]: !isOpen(m) }))
  const setAll = (value: boolean) =>
    setOpenIds(Object.fromEntries(warrants.map((m) => [idOf(m), value])))

  const card = (m: MintedWarrant, children?: React.ReactNode) => (
    <WarrantCard
      key={idOf(m)}
      minted={m}
      root={rootEntry?.warrant}
      all={warrants}
      open={isOpen(m)}
      onToggle={() => toggle(m)}
    >
      {children}
    </WarrantCard>
  )

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
      <div className={`flex items-center justify-between gap-2 ${panelOpen ? 'mb-3' : ''}`}>
        <button
          onClick={() => setPanelOpen(!panelOpen)}
          aria-expanded={panelOpen}
          className="eyebrow text-left hover:text-blue-200"
        >
          <span className="inline-block w-4">{panelOpen ? '▾' : '▸'}</span>Warrant inspector
          {!panelOpen && warrants.length > 0 && (
            <span className="font-sans normal-case tracking-normal text-xs text-gray-500"> · {warrants.length} warrants</span>
          )}
        </button>
        <div className="flex items-center gap-2 shrink-0">
          {panelOpen && warrants.length > 0 && (
            <>
              <button onClick={() => setAll(true)} className="text-[11px] text-gray-500 hover:text-gray-300">
                Expand all
              </button>
              <button onClick={() => setAll(false)} className="text-[11px] text-gray-500 hover:text-gray-300">
                Collapse all
              </button>
            </>
          )}
          <span className="text-xs text-gray-500">{invoiceId}</span>
        </div>
      </div>
      {!panelOpen ? null : warrants.length === 0 ? (
        <div className="text-xs text-gray-600">
          Warrants appear here as the Finance Controller mints them for this invoice.
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-[12px] text-gray-500">
            The Finance Controller holds the root warrant and signs each agent's warrant with its own key.
            A child can only narrow its parent. <span className="text-amber-300">= value</span> pins an
            argument to that one value. Use Raw for every field.
          </div>
          {rootEntry
            ? card(rootEntry, childEntries.length > 0 ? childEntries.map((m) => card(m)) : undefined)
            : childEntries.map((m) => card(m))}
        </div>
      )}
    </div>
  )
}
