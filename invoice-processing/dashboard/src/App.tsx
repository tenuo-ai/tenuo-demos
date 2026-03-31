import { useEffect, useState } from 'react'
import { DemoControls } from './components/DemoControls'
import { ArchitectureDiagram } from './components/ArchitectureDiagram'
import { InvoiceInspector } from './components/InvoiceInspector'
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
  }

  // Act 1 is always the stable overview — architecture + data preview.
  // Acts 2 and 3 switch to the activity view once processing starts.
  const showArchitecture = state.act === 1 || (!hasLogs && !state.running)

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
        {state.act === 3 && state.tenuo_mode === 'cloud' && (
          <span className="text-blue-400 mr-2">Cloud mode — receipts streaming to Tenuo Cloud</span>
        )}
        {state.act === 3 && (
          <a
            href="https://staging.tenuo.ai"
            target="_blank"
            rel="noopener"
            className="text-green-500 hover:text-green-400"
          >
            Open Tenuo Cloud →
          </a>
        )}
      </div>

      {/* Main content */}
      {showArchitecture ? (
        /* Act 1 / pre-run overview: architecture + full data preview */
        <div className="flex-1 flex overflow-hidden">
          <div className="w-1/2 border-r border-gray-800 overflow-y-auto">
            <ArchitectureDiagram />
          </div>
          <div className="w-1/2 overflow-y-auto">
            <InvoiceInspector attackEnabled={false} />
            <div className="border-t border-gray-800">
              <DatabaseState />
            </div>
            {/* Act 1 call-to-action */}
            {state.act === 1 && (
              <div className="p-4 border-t border-gray-800">
                <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-4 text-xs text-gray-400 space-y-2">
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
          </div>
        </div>
      ) : (
        /* During/after processing: activity + invoice inspector + auth + DB */
        <div className="flex-1 flex overflow-hidden">
          {/* Left column: Activity Log */}
          <div className="w-1/2 border-r border-gray-800 flex flex-col">
            <ToolCallLog />
          </div>

          {/* Right column: Invoice Inspector + Auth + DB state */}
          <div className="w-1/2 overflow-y-auto">
            <InvoiceInspector attackEnabled={state.attack_mode !== null} />
            <div className="border-t border-gray-800">
              <AuthDecisionPanel />
            </div>
            <div className="border-t border-gray-800">
              <DatabaseState />
            </div>
            <div className="border-t border-gray-800">
              <LatencyComparison />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
