/**
 * Architecture diagram shown before any batch is processed.
 * Shows the agent graph, tools per agent, and detailed auth stack config.
 */
import { useState } from 'react'

export function ArchitectureDiagram() {
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null)

  return (
    <div className="p-6 overflow-y-auto">
      <h2 className="text-lg font-medium text-gray-200 mb-6">
        AP Automation Pipeline
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
                <div className="text-gray-700 text-[10px]">── delegates ──▶</div>
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
                <div className="text-gray-700 text-[10px]">── delegates ──▶</div>
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
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Authorization Stack — Defense in Depth
          </h3>
          <span className="text-[10px] text-gray-600">
            Every tool call passes through all 4 layers
          </span>
        </div>

        <div className="space-y-2">
          <AuthLayerDetail
            name="Layer 1: GCP Service Accounts + Workload Identity"
            icon="🔑"
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
                <p className="text-green-500/70 text-[10px]">✓ Least-privilege — each agent only has the roles it needs</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 2: OAuth 2.0 Token Exchange"
            icon="🎫"
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
                <p className="text-green-500/70 text-[10px]">✓ Scopes are narrow — invoice-processor can't execute payments, payment-executor can't approve invoices</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 3: SpiceDB (Google Zanzibar)"
            icon="🔗"
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
                <p className="text-green-500/70 text-[10px]">✓ Object-level granularity — agent is editor on specific vendor, not globally</p>
              </div>
            }
          />

          <AuthLayerDetail
            name="Layer 4: OPA Policy Engine (Rego)"
            icon="📜"
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
                <p className="text-green-500/70 text-[10px]">✓ Sophisticated policy — rate-limited, amount-checked, requires justification for bank changes</p>
              </div>
            }
          />
        </div>

        <div className="mt-4 p-3 bg-blue-950/20 border border-blue-900/50 rounded text-xs text-blue-300/80">
          This is not a strawman. Each layer is configured the way a security-conscious enterprise would set it up.
          The question is: what happens when a properly-authorized agent does something it shouldn't?
        </div>
      </div>
    </div>
  )
}

const LEVEL_LABELS: Record<number, string> = { 1: 'L1 Orchestrator', 2: 'L2 Specialist', 3: 'L3 Sub-specialist' }
const COLOR_MAP: Record<string, { bg: string; border: string; text: string }> = {
  blue:   { bg: 'bg-blue-950/40',   border: 'border-blue-700',   text: 'text-blue-400' },
  purple: { bg: 'bg-purple-950/40', border: 'border-purple-700', text: 'text-purple-400' },
  amber:  { bg: 'bg-amber-950/40',  border: 'border-amber-700',  text: 'text-amber-400' },
  green:  { bg: 'bg-green-950/40',  border: 'border-green-700',  text: 'text-green-400' },
  orange: { bg: 'bg-orange-950/40', border: 'border-orange-700', text: 'text-orange-400' },
}

function AgentBox({
  name, level, color, tools, description,
}: {
  name: string; level: number; color: string; tools: string[]; description: string
}) {
  const c = COLOR_MAP[color] || COLOR_MAP.blue
  return (
    <div className={`${c.bg} ${c.border} border rounded-lg p-3 w-60`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-sm font-medium ${c.text}`}>{name}</span>
        <span className="text-[10px] text-gray-600">{LEVEL_LABELS[level]}</span>
      </div>
      <p className="text-[11px] text-gray-500 mb-2">{description}</p>
      <div className="flex flex-wrap gap-1">
        {tools.map((t) => (
          <span
            key={t}
            className={`text-[10px] px-1.5 py-0.5 rounded ${
              t === 'update_vendor_bank'
                ? 'bg-red-900/50 text-red-400 border border-red-800'
                : 'bg-gray-800 text-gray-500'
            }`}
          >
            {t}
          </span>
        ))}
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
        <span className="text-sm">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-200">{name}</div>
          <div className="text-[10px] text-gray-500 truncate">{summary}</div>
        </div>
        <span className="text-gray-600 text-xs">{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 text-[11px] border-t border-gray-800 pt-2">
          {detail}
        </div>
      )}
    </div>
  )
}

function ConfigBlock({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="bg-gray-950 rounded p-2">
      <div className="text-[10px] text-gray-500 mb-1 font-mono">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <span key={item} className="text-[10px] px-1 py-0.5 bg-gray-800 text-gray-400 rounded font-mono">
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="bg-gray-950 rounded p-2 text-[10px] text-gray-400 font-mono overflow-x-auto whitespace-pre">
      {code}
    </pre>
  )
}

function PipelineStep({ step }: { step: number }) {
  return (
    <div className="flex flex-col items-center w-8 flex-shrink-0 pt-3">
      <div className="w-6 h-6 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-[10px] text-gray-400 font-medium">
        {step}
      </div>
      <div className="w-px flex-1 bg-gray-800 mt-1" />
    </div>
  )
}

function PipelineConnector({ label, loop }: { label: string; loop?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="w-8 flex-shrink-0 flex justify-center">
        <div className="w-px h-6 bg-gray-800" />
      </div>
      <div className={`text-[10px] px-2 py-0.5 rounded ${
        loop
          ? 'text-blue-400 bg-blue-950/30 border border-blue-900/50'
          : 'text-gray-500'
      }`}>
        {loop ? `↩ ${label}` : `▼ ${label}`}
      </div>
    </div>
  )
}
