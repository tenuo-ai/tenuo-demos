import { useEffect, useState } from 'react'
import { DemoControls } from './components/DemoControls'
import { ArchitectureDiagram } from './components/ArchitectureDiagram'
import { InvoiceInspector } from './components/InvoiceInspector'
import { AuthDecisionPanel } from './components/AuthDecisionPanel'
import { ToolCallLog } from './components/ToolCallLog'
import { DatabaseState } from './components/DatabaseState'
import { LatencyComparison } from './components/LatencyComparison'
import { WarrantChain } from './components/WarrantChain'
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

  const handleStateChange = (newState: DemoState) => {
    setState(newState)
    // Reset logs flag when state changes (act switch resets DB)
    if (newState.act !== state.act) {
      setHasLogs(false)
    }
  }

  // Show architecture diagram when no processing has happened yet
  const showArchitecture = !hasLogs && !state.running

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <DemoControls state={state} onStateChange={handleStateChange} />

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
            href="https://cloud.tenuo.ai"
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
        /* Before processing: show architecture + invoice inspector */
        <div className="flex-1 flex overflow-hidden">
          <div className="w-1/2 border-r border-gray-800 overflow-y-auto">
            <ArchitectureDiagram />
          </div>
          <div className="w-1/2 overflow-y-auto">
            <InvoiceInspector attackEnabled={state.attack_mode !== null} />
          </div>
        </div>
      ) : (
        /* During/after processing: activity + invoice inspector + auth + DB */
        <div className="flex-1 flex overflow-hidden">
          {/* Left column: Activity Log */}
          <div className="w-1/2 border-r border-gray-800 flex flex-col">
            <ToolCallLog events={events} />
          </div>

          {/* Right column: Invoice Inspector + Auth + DB state */}
          <div className="w-1/2 overflow-y-auto">
            <InvoiceInspector attackEnabled={state.attack_mode !== null} />
            <div className="border-t border-gray-800">
              <WarrantChain />
            </div>
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
