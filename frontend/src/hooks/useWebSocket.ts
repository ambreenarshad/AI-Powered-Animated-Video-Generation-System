import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url: string) {
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'log') {
          setLogs((prev) => [...prev.slice(-999), data.message as string])
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onclose = () => {
      setConnected(false)
      reconnectRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clearLogs = useCallback(() => setLogs([]), [])

  return { logs, connected, clearLogs }
}
