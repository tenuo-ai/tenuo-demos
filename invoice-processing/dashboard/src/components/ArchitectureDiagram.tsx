/**
 * Architecture diagram shown before any batch is processed.
 * Shows the agent graph, tools per agent, and detailed auth stack config.
 */
import { useState } from 'react'

export function ArchitectureDiagram() {
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null)

  return (
    <div className="p-6 overflow-y-auto">
      <h2 className="font-display text-lg font-semibold text-gray-50 mb-6">
        Accounts Payable Automation Pipeline
      </h2>

      {/* Agent pipeline — shows actual sequential flow with delegation branches */}
      <div className="mb-8">
        {/* Step 1: Finance Controller */}
        <div className="flex items-start gap-3">
          <PipelineStep step={1} />
          <div className="flex-1">
            <AgentBox
              name="Finance Controller"
              level={1}
              color="blue"
              tools={['list_invoices', 'read_invoice']}
              description="Orchestrator — receives invoice batch, processes each invoice sequentially"
            />
          </div>
        </div>

        <PipelineConnector label="for each invoice" />

        {/* Step 2: Invoice Processor (with delegation branch to Vendor Verification) */}
        <div className="flex items-start gap-3">
          <PipelineStep step={2} />
          <div className="flex-1">
            <div className="flex items-start gap-3">
              <AgentBox
                name="Invoice Processor"
                level={2}
                color="purple"
                tools={['read_invoice', 'read_po', 'lookup_vendor', 'verify_vendor', 'update_vendor_bank', 'approve_invoice']}
                description="Reads invoice, verifies vendor, checks PO, approves"
              />
              {/* Delegation branch */}
              <div className="flex items-center gap-2 mt-6">
                <div className="font-mono text-[11px] text-gray-500 whitespace-nowrap">── delegates ──▶</div>
                <AgentBox
                  name="Vendor Verification"
                  level={3}
                  color="green"
                  tools={['lookup_vendor', 'verify_vendor']}
                  description="Read-only vendor check"
                />
              </div>
            </div>
          </div>
        </div>

        <PipelineConnector label="invoice approved" />

        {/* Step 3: Payment Executor (with delegation branch to FX Rate Checker) */}
        <div className="flex items-start gap-3">
          <PipelineStep step={3} />
          <div className="flex-1">
            <div className="flex items-start gap-3">
              <AgentBox
                name="Payment Executor"
                level={2}
                color="amber"
                tools={['initiate_payment', 'approve_payment', 'get_fx_rate']}
                description="Initiates and approves payment for the invoice"
              />
              {/* Delegation branch */}
              <div className="flex items-center gap-2 mt-6">
                <div className="font-mono text-[11px] text-gray-500 whitespace-nowrap">── delegates ──▶</div>
                <AgentBox
                  name="FX Rate Checker"
                  level={3}
                  color="orange"
                  tools={['get_fx_rate']}
                  description="For international payments"
                />
              </div>
            </div>
          </div>
        </div>

        <PipelineConnector label="next invoice" loop />
      </div>

      {/* Auth stack — detailed */}
      <div className="border-t border-gray-800 pt-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="eyebrow">
            Authorization Stack — Defense in Depth
          </h3>
          <span className="text-[11px] text-gray-600">
            Every tool call passes through all 4 layers
          </span>
        </div>

        <div className="space-y-2">
          <AuthLayerDetail
            name="Layer 1: GCP Service Accounts + Workload Identity"
            icon="L1"
            expanded={expandedLayer === 'gcp'}
            onToggle={() => setExpandedLayer(expandedLayer === 'gcp' ? null : 'gcp')}
            summary="Per-agent identity with least-privilege IAM roles"
            detail={
              <div className="space-y-2">
                <p className="text-gray-400">Each agent runs as a separate GCP service account with Workload Identity Federation. Roles are scoped per agent type:</p>
                <div className="grid grid-cols-2 gap-2">
                  <ConfigBlock label="invoice-processor" items={['ap.processor', 'vendor.reader', 'vendor.editor', 'cloudsql.client']} />
                  <ConfigBlock label="payment-executor" items={['ap.payment', 'cloudsql.client']} />
                  <ConfigBlock label="vendor-verification" items={['vendor.reader', 'vendor.editor', 'cloudsql.client']} />
                  <ConfigBlock label="fx-rate-checker" items={['fx.reader']} />
                </div>
                <p className="text-green-500/70 text-[11px]">✓ Least-privilege — each agent only has the roles it needs</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 2: OAuth 2.0 Token Exchange"
            icon="L2"
            expanded={expandedLayer === 'oauth'}
            onToggle={() => setExpandedLayer(expandedLayer === 'oauth' ? null : 'oauth')}
            summary="Narrow scopes per resource type — invoices:read, vendors:write, payments:execute"
            detail={
              <div className="space-y-2">
                <p className="text-gray-400">Token exchange with granular scopes. Each scope maps to a specific resource category:</p>
                <div className="grid grid-cols-2 gap-2">
                  <ConfigBlock label="invoice-processor" items={['invoices:read', 'invoices:write', 'vendors:read', 'vendors:write', 'po:read']} />
                  <ConfigBlock label="payment-executor" items={['invoices:read', 'payments:read', 'payments:execute', 'vendors:read', 'fx:read']} />
                </div>
                <p className="text-green-500/70 text-[11px]">✓ Scopes are narrow — invoice-processor can't execute payments, payment-executor can't approve invoices</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 3: SpiceDB (Google Zanzibar)"
            icon="L3"
            expanded={expandedLayer === 'spicedb'}
            onToggle={() => setExpandedLayer(expandedLayer === 'spicedb' ? null : 'spicedb')}
            summary="Relationship-based RBAC — object-level granularity, not just roles"
            detail={
              <div className="space-y-2">
                <p className="text-gray-400">Zanzibar-style relationship tuples. Authorization is checked against specific objects, not just roles:</p>
                <CodeBlock code={`definition vendor {
    relation viewer: agent
    relation editor: agent    // needed for verification workflow

    permission read = viewer + editor
    permission verify = editor
    permission update_bank = editor  // same permission as verify
}

// Relationships:
vendor:V-4521#editor@agent:invoice-processor
vendor:V-4521#editor@agent:vendor-verification`} />
                <p className="text-green-500/70 text-[11px]">✓ Object-level granularity — agent is editor on specific vendor, not globally</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 4: OPA Policy Engine (Rego)"
            icon="L4"
            expanded={expandedLayer === 'opa'}
            onToggle={() => setExpandedLayer(expandedLayer === 'opa' ? null : 'opa')}
            summary="Context-aware policies with rate limits, amount thresholds, vendor verification requirements"
            detail={
              <div className="space-y-2">
                <p className="text-gray-400">Real OPA instance evaluating Rego policies. Includes multi-attribute checks:</p>
                <CodeBlock code={`allow {
    has_required_role          # agent has correct role
    within_amount_threshold    # amount < $50k for processors
    passes_vendor_checks       # bank updates need detailed reason
    passes_rate_limit          # max 20 operations/hour
}

# Vendor bank updates require justification:
passes_vendor_checks {
    input.tool_name == "update_vendor_bank"
    input.tool_args.reason
    count(input.tool_args.reason) > 10  # needs detail
}`} />
                <p className="text-green-500/70 text-[11px]">✓ Sophisticated policy — rate-limited, amount-checked, requires justification for bank changes</p>
              </div>
            }
          />
        </div>

        <div className="mt-4 p-3 bg-blue-950/20 border border-blue-900/50 rounded text-xs text-blue-300/80 space-y-1">
          <div>Not a strawman — each layer is correctly configured for enterprise use.</div>
          <div className="text-blue-200/90">
            All 4 ask <span className="italic">"is this agent authorized?"</span> — none ask <span className="italic">"was this capability delegated for this task?"</span> That's the gap.
          </div>
        </div>
      </div>
    </div>
  )
}

const LEVEL_LABELS: Record<number, string> = { 1: 'L1 · Orchestrator', 2: 'L2 · Specialist', 3: 'L3 · Sub-specialist' }
// Per-agent accent, as on tenuo.ai: a solid brand-colour strip, a coloured
// title, and tool chips tinted in the same hue. Each class resolves per theme.
const COLOR_MAP: Record<string, { bar: string; title: string; chip: string }> = {
  blue:   { bar: 'bg-blue-600',   title: 'text-blue-400',   chip: 'bg-blue-950 text-blue-300 border-blue-800' },
  purple: { bar: 'bg-purple-600', title: 'text-purple-400', chip: 'bg-purple-950 text-purple-300 border-purple-800' },
  amber:  { bar: 'bg-amber-600',  title: 'text-amber-400',  chip: 'bg-amber-950 text-amber-300 border-amber-800' },
  green:  { bar: 'bg-green-600',  title: 'text-green-400',  chip: 'bg-green-950 text-green-300 border-green-800' },
  orange: { bar: 'bg-orange-600', title: 'text-orange-400', chip: 'bg-orange-950 text-orange-300 border-orange-800' },
}

function AgentBox({
  name, level, color, tools, description,
}: {
  name: string; level: number; color: string; tools: string[]; description: string
}) {
  const c = COLOR_MAP[color] || COLOR_MAP.blue
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg w-64 overflow-hidden shadow-sm">
      <div className={`h-1 ${c.bar}`} />
      <div className="p-3">
        <div className={`font-mono text-[10px] uppercase tracking-[0.12em] mb-0.5 ${c.title}`}>
          {LEVEL_LABELS[level]}
        </div>
        <div className={`font-display text-base font-semibold leading-tight mb-1 ${c.title}`}>{name}</div>
        <p className="text-[12px] text-gray-400 mb-2.5">{description}</p>
        <div className="flex flex-wrap gap-1">
          {tools.map((t) => (
            <span
              key={t}
              className={`font-mono text-[11px] px-1.5 py-0.5 rounded border ${
                t === 'update_vendor_bank'
                  ? 'bg-red-950 text-red-400 border-red-600 font-medium'
                  : c.chip
              }`}
            >
              {t}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function AuthLayerDetail({
  name, icon, summary, detail, expanded, onToggle,
}: {
  name: string; icon: string; summary: string; detail: React.ReactNode
  expanded: boolean; onToggle: () => void
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2.5 flex items-center gap-2 text-left hover:bg-gray-800/50 transition-colors"
      >
        <span className="w-7 shrink-0 text-center font-mono text-[11px] font-medium py-px rounded border border-blue-800 text-blue-300">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-200">{name}</div>
          <div className="text-[11px] text-gray-500 truncate">{summary}</div>
        </div>
        <span className="text-gray-600 text-xs">{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 text-[12px] border-t border-gray-800 pt-2">
          {detail}
        </div>
      )}
    </div>
  )
}

function ConfigBlock({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="bg-gray-950 rounded p-2">
      <div className="text-[11px] text-gray-500 mb-1 font-mono">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <span key={item} className="text-[11px] px-1 py-0.5 bg-gray-800 text-gray-400 rounded font-mono">
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="bg-gray-950 rounded p-2 text-[11px] text-gray-400 font-mono overflow-x-auto whitespace-pre">
      {code}
    </pre>
  )
}

function PipelineStep({ step }: { step: number }) {
  return (
    <div className="flex flex-col items-center w-8 flex-shrink-0 pt-3">
      <div className="w-6 h-6 rounded-full bg-blue-950 border border-blue-600 flex items-center justify-center font-mono text-[11px] text-blue-400 font-medium">
        {step}
      </div>
      <div className="w-px flex-1 bg-gray-700 mt-1" />
    </div>
  )
}

function PipelineConnector({ label, loop }: { label: string; loop?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="w-8 flex-shrink-0 flex justify-center">
        <div className="w-px h-6 bg-gray-700" />
      </div>
      <div className={`text-[11px] px-2 py-0.5 rounded ${
        loop
          ? 'text-blue-400 bg-blue-950/30 border border-blue-900/50'
          : 'text-gray-400'
      }`}>
        {loop ? `↩ ${label}` : `▼ ${label}`}
      </div>
    </div>
  )
}
