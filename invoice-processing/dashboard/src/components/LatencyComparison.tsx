import { useEffect, useState } from 'react'

interface LayerLatency {
  avg_us: number
  n: number
}

const LAYER_LABELS: Record<string, string> = {
  opa: 'OPA — one HTTP round-trip to policy engine',
  tenuo: 'Tenuo — in-process warrant check (no network)',
}

const LAYER_COLORS = {
  opa: { bar: 'bg-yellow-500', text: 'text-yellow-400' },
  tenuo: { bar: 'bg-green-500', text: 'text-green-400' },
}

export function LatencyComparison() {
  const [latency, setLatency] = useState<Record<string, LayerLatency>>({})

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/db/auth-latency')
        const data = await res.json()
        setLatency(data)
      } catch {
        // ignore — show stale data on transient errors
      }
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
  }, [])

  const opa = latency['opa']
  const tenuo = latency['tenuo']
  const opaUs = opa?.avg_us ?? 0
  const tenuoUs = tenuo?.avg_us ?? 0
  const hasData = opaUs > 0 || tenuoUs > 0
  const maxUs = Math.max(opaUs, tenuoUs, 1)

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
        Authorization Latency
      </h2>

      {!hasData ? (
        <div className="text-gray-600 text-sm">
          Latency data will appear after processing a batch.
        </div>
      ) : (
        <div className="space-y-3">
          {(['opa', 'tenuo'] as const).map((layer) => {
            const us = layer === 'opa' ? opaUs : tenuoUs
            if (us === 0) return null
            const meta = latency[layer]
            const colors = LAYER_COLORS[layer]
            return (
              <div key={layer}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-500">
                    {LAYER_LABELS[layer]}
                    {meta && <span className="text-gray-700 ml-1">({meta.n} checks)</span>}
                  </span>
                  <span className={`font-mono ${colors.text}`}>{us.toLocaleString()}μs</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${colors.bar} rounded-full transition-all duration-500`}
                    style={{ width: `${(us / maxUs) * 100}%` }}
                  />
                </div>
              </div>
            )
          })}

          {opaUs > 0 && tenuoUs > 0 && (
            <div className="pt-1 text-xs text-gray-500">
              Tenuo is{' '}
              <span className="text-green-400 font-medium">
                {(opaUs / tenuoUs).toFixed(1)}x faster
              </span>{' '}
              per authorization check
            </div>
          )}
        </div>
      )}
    </div>
  )
}
