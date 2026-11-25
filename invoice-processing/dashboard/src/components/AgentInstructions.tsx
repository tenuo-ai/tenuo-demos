/**
 * Agent instructions panel: shows the Invoice Processor's system prompt.
 *
 * Used for the "prompt" attack, where the invoice is clean and the attack
 * lives in the agent's own instructions. The block the attacker appended is
 * highlighted so the presenter can say: "The invoice is fine. Someone edited
 * the agent's instructions."
 */
import { useEffect, useState } from 'react'

interface Instructions {
  attack_mode: string | null
  tampered: boolean
  instructions: string
  tampered_block: string | null
}

export function AgentInstructions({ attackMode }: { attackMode: string | null }) {
  const [data, setData] = useState<Instructions | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    fetch('/api/agent-instructions/invoice-processor')
      .then((res) => res.json())
      .then(setData)
      .catch(() => setData(null))
  }, [attackMode])

  if (!data) return null

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="eyebrow">
          Invoice Processor instructions
        </h2>
        {data.tampered && (
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-red-900/50 text-red-400 border border-red-800">
            Tampered by attacker
          </span>
        )}
      </div>

      <div className="text-xs rounded border border-gray-800 bg-gray-900 font-mono whitespace-pre-wrap">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full text-left px-3 py-2 text-gray-500 hover:text-gray-300"
        >
          {expanded ? '▾' : '▸'} Standard operating procedure (unchanged)
        </button>
        {expanded && <div className="px-3 pb-3 text-gray-400">{data.instructions}</div>}

        {data.tampered_block && (
          <div className="px-3 py-3 border-t border-red-800 bg-red-950/30 text-red-300">
            <div className="eyebrow text-[11px] text-red-400 mb-2">
              Added by attacker
            </div>
            {data.tampered_block}
          </div>
        )}
      </div>
    </div>
  )
}
