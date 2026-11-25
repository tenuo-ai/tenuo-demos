import { useEffect, useState } from 'react'
import { DemoControls } from './components/DemoControls'
import { ArchitectureDiagram } from './components/ArchitectureDiagram'
import { InvoiceInspector } from './components/InvoiceInspector'
import { AgentInstructions } from './components/AgentInstructions'
import { WarrantInspector } from './components/WarrantInspector'
import { AuthDecisionPanel } from './components/AuthDecisionPanel'
import { ToolCallLog } from './components/ToolCallLog'
import { DatabaseState } from './components/DatabaseState'
import { LatencyComparison } from './components/LatencyComparison'
import { useEventStream } from './hooks/useEventStream'
import { fetchState, fetchAgentLogs } from './lib/api'
import type { DemoState } from './lib/types'

export default function App() {
  const { events, connected } = useEventStream()
  const [state, setState] = useState<DemoState>({
    act: 1,
    attack_mode: null,
    auth_stack: 'standard',
    tenuo_mode: 'local',
    running: false,
  })
  const [hasLogs, setHasLogs] = useState(false)
  const [selectedInvoice, setSelectedInvoice] = useState('INV-2024-1847')
  // Left panel: the pipeline diagram or the activity log. Until the presenter
  // picks one it follows the run (pipeline before, log once a run starts);
  // after a pick it stays put.
  const [leftChoice, setLeftChoice] = useState<'pipeline' | 'logs' | null>(null)
  const [showLeft, setShowLeft] = useState(true)
  const [demoError, setDemoError] = useState<string | null>(null)

  // Fetch initial state
  useEffect(() => {
    fetchState().then(setState)
  }, [])

  // Poll API state to reliably sync running status
  // (SSE-based reset alone can miss events published before subscription)
  useEffect(() => {
    const poll = async () => {
      try {
        const s = await fetchState()
        setState((prev) => ({ ...prev, running: s.running }))
      } catch {
        // ignore
      }
    }
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  // Poll for logs to know when to switch from architecture to activity view
  useEffect(() => {
    const poll = async () => {
      try {
        const logs = await fetchAgentLogs()
        setHasLogs(logs.length > 0)
      } catch {
        // ignore
      }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [])

  // Reset running state when the server signals completion or error
  useEffect(() => {
    const last = events[events.length - 1]
    if (!last) return
    if (last.type === 'demo_completed' || last.type === 'demo_error') {
      setState((s) => ({ ...s, running: false }))
    }
    if (last.type === 'demo_error') {
      setDemoError((last as { error?: string }).error ?? 'Unknown error')
    }
    if (last.type === 'demo_completed') {
      setDemoError(null)
    }
  }, [events])

  const handleStateChange = (newState: DemoState) => {
    setState(newState)
    // Clear logs on act change (act switch resets DB)
    if (newState.act !== state.act) {
      setHasLogs(false)
    }
  }

  const handleReset = (newState: DemoState) => {
    setState(newState)
    setHasLogs(false)  // reset always wipes the DB
    setDemoError(null)
  }

  // Act 1 is always the stable overview; Acts 2 and 3 show the run panels
  // (warrants, decisions, latency) on the right once processing starts.
  const showArchitecture = state.act === 1 || (!hasLogs && !state.running)
  const leftPanel = leftChoice ?? (showArchitecture ? 'pipeline' : 'logs')
  const pickLeft = (panel: 'pipeline' | 'logs') => {
    setLeftChoice(panel)
    setShowLeft(true)
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <DemoControls state={state} onStateChange={handleStateChange} onReset={handleReset} />

      {/* Status bar */}
      <div className="px-4 py-1 text-xs flex items-center gap-2 border-b border-gray-900">
        <div
          className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500 animate-pulse'}`}
        />
        <span className="text-gray-600">
          {connected ? 'Connected' : 'Reconnecting...'}
        </span>
        {state.running && (
          <span className="text-blue-400 ml-2 animate-pulse">Processing batch...</span>
        )}
        <div className="flex-1" />
        <div role="group" aria-label="Left panel" className="flex rounded border border-gray-700 overflow-hidden">
          {(['pipeline', 'logs'] as const).map((panel) => (
            <button
              key={panel}
              onClick={() => pickLeft(panel)}
              aria-pressed={showLeft && leftPanel === panel}
              className={`px-2.5 py-0.5 transition-colors ${
                showLeft && leftPanel === panel
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`}
            >
              {panel === 'pipeline' ? 'Pipeline' : 'Activity log'}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowLeft(!showLeft)}
          aria-pressed={!showLeft}
          className="mr-3 px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
        >
          {showLeft ? 'Hide panel' : 'Show panel'}
        </button>
        {state.act === 3 && state.tenuo_mode === 'cloud' && !demoError && (
          <span className="text-blue-400 mr-2">Cloud mode — receipts streaming to Tenuo Cloud</span>
        )}
        {state.act === 3 && (
          <a
            href="https://cloud.tenuo.ai"
            target="_blank"
            rel="noopener"
            className="text-green-500 hover:text-green-400"
          >
            Open Tenuo Cloud →
          </a>
        )}
      </div>

      {/* Error banner — shown below status bar when a run fails */}
      {demoError && !state.running && (
        <div className="px-4 py-2.5 bg-red-950/60 border-b border-red-800/50 flex items-start gap-3">
          <span className="text-red-400 text-sm mt-0.5 shrink-0">⚠</span>
          <div className="flex-1 min-w-0">
            <span className="text-red-300 text-xs">{demoError}</span>
          </div>
          <button
            onClick={() => setDemoError(null)}
            className="text-red-600 hover:text-red-400 text-xs shrink-0 mt-0.5"
            title="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main content: left panel (pipeline or activity log, from the status bar)
          and the right column, which shows the overview before a run and the run
          panels once processing starts. */}
      <div className="flex-1 flex overflow-hidden">
        {showLeft && (
          leftPanel === 'pipeline' ? (
            <div className="w-1/2 border-r border-gray-800 overflow-y-auto">
              <ArchitectureDiagram />
            </div>
          ) : (
            <div className="w-1/2 border-r border-gray-800 flex flex-col">
              <ToolCallLog />
            </div>
          )
        )}

        <div className={`${showLeft ? 'w-1/2' : 'w-full'} overflow-y-auto`}>
          {showArchitecture ? (
            <>
              <InvoiceInspector
                attackMode={state.attack_mode}
                attackEnabled={false}
                selected={selectedInvoice}
                onSelect={setSelectedInvoice}
              />
              {state.attack_mode === 'prompt' && (
                <div className="border-t border-gray-800">
                  <AgentInstructions attackMode={state.attack_mode} />
                </div>
              )}
              <div className="border-t border-gray-800">
                <DatabaseState act={state.act} />
              </div>
              {/* Act 1 call-to-action */}
              {state.act === 1 && (
                <div className="p-4 border-t border-gray-800">
                  <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 text-xs text-gray-400 space-y-2">
                    <div className="text-gray-200 font-medium text-sm">Ready to demo</div>
                    <div>
                      <span className="text-red-400 font-medium">Act 2 →</span> Select an attack mode and run the batch to see the 4-layer stack approve every step.
                    </div>
                    <div>
                      <span className="text-green-400 font-medium">Act 3 →</span> Add Tenuo to see warrants attenuate in real time and the attack get blocked cryptographically.
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <InvoiceInspector
                attackMode={state.attack_mode}
                attackEnabled={state.attack_mode === 'injection'}
                selected={selectedInvoice}
                onSelect={setSelectedInvoice}
              />
              {state.attack_mode === 'prompt' && (
                <div className="border-t border-gray-800">
                  <AgentInstructions attackMode={state.attack_mode} />
                </div>
              )}
              {state.auth_stack === 'tenuo' && (
                <div className="border-t border-gray-800">
                  <WarrantInspector invoiceId={selectedInvoice} />
                </div>
              )}
              <div className="border-t border-gray-800">
                <AuthDecisionPanel />
              </div>
              <div className="border-t border-gray-800">
                <DatabaseState act={state.act} />
              </div>
              <div className="border-t border-gray-800">
                <LatencyComparison />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
