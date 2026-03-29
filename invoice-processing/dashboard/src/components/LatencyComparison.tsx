import { useEffect, useState } from 'react'
import { fetchAuthDecisions } from '../lib/api'

export function LatencyComparison() {
  const [opaLatency, setOpaLatency] = useState<number>(0)
  const [tenuoLatency, setTenuoLatency] = useState<number>(0)

  useEffect(() => {
    const poll = async () => {
      try {
        const decisions = await fetchAuthDecisions()
        const opaDecisions = decisions.filter(
          (d: { layer: string; latency_us: number }) => d.layer === 'opa'
        )
        const tenuoDecisions = decisions.filter(
          (d: { layer: string; latency_us: number }) => d.layer === 'tenuo'
        )
        if (opaDecisions.length > 0) {
          const avg =
            opaDecisions.reduce((sum: number, d: { latency_us: number }) => sum + d.latency_us, 0) /
            opaDecisions.length
          setOpaLatency(Math.round(avg))
        }
        if (tenuoDecisions.length > 0) {
          const avg =
            tenuoDecisions.reduce((sum: number, d: { latency_us: number }) => sum + d.latency_us, 0) /
            tenuoDecisions.length
          setTenuoLatency(Math.round(avg))
        }
      } catch {
        // ignore
      }
    }
    poll()
    const interval = setInterval(poll, 5000)
    return () => clearInterval(interval)
  }, [])

  // Don't render if no data yet
  if (opaLatency === 0 && tenuoLatency === 0) {
    return (
      <div className="p-4">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
          Authorization Latency
        </h2>
        <div className="text-gray-600 text-sm">
          Latency data will appear after processing a batch.
        </div>
      </div>
    )
  }

  const maxLatency = Math.max(opaLatency, tenuoLatency, 1)

  return (
    <div className="p-4">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
        Authorization Latency
      </h2>
      <div className="space-y-3">
        {opaLatency > 0 && (
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-gray-500">OPA (network round-trip)</span>
              <span className="text-yellow-400">{opaLatency.toLocaleString()}μs</span>
            </div>
            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-yellow-500 rounded-full transition-all"
                style={{ width: `${(opaLatency / maxLatency) * 100}%` }}
              />
            </div>
          </div>
        )}
        {tenuoLatency > 0 && (
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-gray-500">Tenuo (in-process SDK)</span>
              <span className="text-green-400">{tenuoLatency}μs</span>
            </div>
            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${(tenuoLatency / maxLatency) * 100}%` }}
              />
            </div>
          </div>
        )}
        {opaLatency > 0 && tenuoLatency > 0 && (
          <div className="text-xs text-gray-500 mt-2">
            Tenuo is{' '}
            <span className="text-green-400 font-medium">
              {Math.round(opaLatency / tenuoLatency)}x faster
            </span>{' '}
            — no network round-trip needed
          </div>
        )}
      </div>
    </div>
  )
}
