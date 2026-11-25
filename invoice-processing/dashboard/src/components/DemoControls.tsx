import type { DemoState } from '../lib/types'
import { setAct, setAttackMode, setTenuoMode, startDemo, resetDemo } from '../lib/api'
import { useTheme } from '../lib/theme'

const ATTACK_LABELS: Record<string, string> = {
  off: 'Off',
  injection: 'Injection',
  prompt: 'Prompt',
  simulate: 'Simulate',
}

const ATTACK_DESCRIPTIONS: Record<string, string> = {
  off: 'No attack: clean invoices, standard instructions',
  injection: 'Poisoned invoice: the vendor portal serves INV-2024-1847 with a fake bank-change note',
  prompt: "Tampered instructions: the invoice is clean, but the attacker edited the Invoice Processor's system prompt",
  simulate: 'Simulated compromise: calls update_vendor_bank directly, without the LLM, to test the auth layers in isolation',
}

interface Props {
  state: DemoState
  onStateChange: (state: DemoState) => void
  onReset: (state: DemoState) => void
}

export function DemoControls({ state, onStateChange, onReset }: Props) {
  const [theme, toggleTheme] = useTheme()
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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 bg-navy border-b border-gray-800">
      {/* Brand */}
      <div className="flex items-center gap-3 pr-4 border-r border-gray-800">
        {/* White wordmark on navy, dark wordmark on white, as on tenuo.ai */}
        <img
          src={theme === 'dark' ? '/tenuo-logo-light.png' : '/tenuo-logo.png'}
          alt="Tenuo"
          className="h-5 w-auto"
        />
        <span className="hidden 2xl:inline font-display text-[14px] font-semibold text-gray-200 whitespace-nowrap">
          Invoice processing demo
        </span>
      </div>

      {/* Act selector */}
      <div className="flex items-center gap-2">
        <span className="hidden 2xl:inline eyebrow text-[12px] text-gray-500">Act</span>
        {[1, 2, 3].map((act) => (
          <button
            key={act}
            onClick={() => handleAct(act)}
            className={`px-3 py-1 text-[14px] font-medium rounded whitespace-nowrap transition-colors ${
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
          <span className="hidden 2xl:inline eyebrow text-[12px] text-gray-500">Attack</span>
          {['off', 'injection', 'prompt', 'simulate'].map((mode) => (
            <button
              key={mode}
              onClick={() => handleAttack(mode)}
              title={ATTACK_DESCRIPTIONS[mode]}
              className={`px-3 py-1 text-[14px] font-medium rounded whitespace-nowrap transition-colors ${
                (state.attack_mode ?? 'off') === mode
                  ? mode === 'off'
                    ? 'bg-gray-600 text-white'
                    : 'bg-red-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {ATTACK_LABELS[mode]}
            </button>
          ))}
        </div>
      )}

      {/* Auth stack indicator */}
      <div className="flex items-center gap-2">
        <span className="hidden 2xl:inline eyebrow text-[12px] text-gray-500">Auth</span>
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
          <span className="hidden 2xl:inline eyebrow text-[12px] text-gray-500">Mode</span>
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
              className={`px-3 py-1 text-[14px] font-medium rounded whitespace-nowrap transition-colors ${
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

      {/* Actions stay on the right, also when the bar wraps */}
      <div className="ml-auto flex items-center gap-2">

      {/* Action buttons — hidden in Act 1 (overview only) */}
      {state.act !== 1 && (
        <button
          onClick={handleStart}
          disabled={state.running}
          className={`px-5 py-2 rounded font-bold whitespace-nowrap transition-colors ${
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
        className="px-4 py-2 rounded font-bold whitespace-nowrap border border-gray-700 text-gray-200 hover:bg-gray-800 transition-colors"
      >
        Reset
      </button>
      <button
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        className="p-2 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 transition-colors"
      >
        {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
      </button>
      </div>
    </div>
  )
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}
