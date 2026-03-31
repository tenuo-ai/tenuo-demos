import { useEffect, useRef, useState, useCallback } from 'react'
import type { DemoEvent } from '../lib/types'

export function useEventStream() {
  const [events, setEvents] = useState<DemoEvent[]>([])
  const [connected, setConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const es = new EventSource('/events')
    eventSourceRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.onmessage = (e) => {
      try {
        const event: DemoEvent = JSON.parse(e.data)
        setEvents((prev) => [...prev.slice(-200), event]) // Keep last 200 events
      } catch {
        // Ignore malformed events
      }
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [])

  const clearEvents = useCallback(() => setEvents([]), [])

  return { events, connected, clearEvents }
}
