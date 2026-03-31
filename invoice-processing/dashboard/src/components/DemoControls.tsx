import type { DemoState } from '../lib/types'
import { setAct, setAttackMode, setTenuoMode, startDemo, resetDemo } from '../lib/api'

interface Props {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onReset: (state: DemoState) => void
}

export function DemoControls({ state, onStateChange, onReset }: Props) {
  const handleAct = async (act: number) => {
    const s = await setAct(act)
    onStateChange(s)
  }

  const handleAttack = async (mode: string) => {
    const s = await setAttackMode(mode)
    onStateChange(s)
  }

  const handleStart = async () => {
    await startDemo()
    onStateChange({ ...state, running: true })
  }

  const handleReset = async () => {
    const s = await resetDemo()
    onReset(s)
  }

  return (
    <div className="flex items-center gap-6 p-4 bg-gray-900 border-b border-gray-800">
      {/* Act selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Act</span>
        {[1, 2, 3].map((act) => (
          <button
            key={act}
            onClick={() => handleAct(act)}
            className={`px-3 py-1 text-sm rounded transition-colors ${
              state.act === act
                ? act === 1
                  ? 'bg-blue-600 text-white'
                  : act === 2
                    ? 'bg-red-600 text-white'
                    : 'bg-green-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            {act === 1 ? '1: The App' : act === 2 ? '2: The Attack' : '3: Tenuo'}
          </button>
        ))}
      </div>

      {/* Attack mode — hidden in Act 1 */}
      {state.act !== 1 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Attack</span>
          {['off', 'injection', 'prompt', 'simulate'].map((mode) => (
            <button
              key={mode}
              onClick={() => handleAttack(mode)}
              title={
                mode === 'simulate'
                  ? 'Directly calls update_vendor_bank without LLM involvement — tests the auth layer in isolation'
                  : undefined
              }
              className={`px-3 py-1 text-sm rounded transition-colors ${
                (state.attack_mode ?? 'off') === mode
                  ? mode === 'off'
                    ? 'bg-gray-600 text-white'
                    : 'bg-red-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      )}

      {/* Auth stack indicator */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Auth</span>
        <span
          className={`px-3 py-1 text-sm rounded ${
            state.auth_stack === 'tenuo'
              ? 'bg-green-700 text-white'
              : 'bg-gray-700 text-gray-300'
          }`}
        >
          {state.auth_stack === 'tenuo' ? 'Tenuo + Standard' : 'Standard (4-layer)'}
        </span>
      </div>

      {/* Tenuo mode toggle — visible in Act 3 */}
      {state.act === 3 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Mode</span>
          {['local', 'cloud'].map((mode) => (
            <button
              key={mode}
              onClick={async () => {
                const s = await setTenuoMode(mode)
                onStateChange(s)
              }}
              title={
                mode === 'cloud'
                  ? 'Requires Tenuo Cloud credentials — see README for setup'
                  : undefined
              }
              className={`px-3 py-1 text-sm rounded transition-colors ${
                state.tenuo_mode === mode
                  ? mode === 'cloud'
                    ? 'bg-blue-600 text-white'
                    : 'bg-green-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {mode === 'local' ? 'Local SDK' : 'Tenuo Cloud ↗'}
            </button>
          ))}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Action buttons — hidden in Act 1 (overview only) */}
      {state.act !== 1 && (
        <button
          onClick={handleStart}
          disabled={state.running}
          className={`px-5 py-2 rounded font-medium transition-colors ${
            state.running
              ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-500'
          }`}
        >
          {state.running ? 'Processing...' : 'Process Batch'}
        </button>
      )}
      <button
        onClick={handleReset}
        className="px-4 py-2 rounded font-medium bg-gray-800 text-gray-300 hover:bg-gray-700 transition-colors"
      >
        Reset
      </button>
    </div>
  )
}
