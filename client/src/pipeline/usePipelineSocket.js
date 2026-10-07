import { useCallback, useEffect, useRef, useState } from 'react'
import { pipelineWsUrl } from './pipelineApi'
import { normalizeEvent } from './eventNormalizer'

const MAX_EVENTS = 500
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000

export function usePipelineSocket({ enabled = true } = {}) {
  const [events, setEvents] = useState([])
  const [status, setStatus] = useState('idle')
  const [paused, setPausedState] = useState(false)
  const [bufferedCount, setBufferedCount] = useState(0)

  const pausedRef = useRef(false)
  const bufferRef = useRef([])
  const seenRef = useRef(new Set())
  const wsRef = useRef(null)
  const retryRef = useRef(0)
  const reconnectTimerRef = useRef(null)
  const aliveRef = useRef(false)

  const setPaused = useCallback((next) => {
    setPausedState((prev) => {
      const value = typeof next === 'function' ? next(prev) : next
      pausedRef.current = value
      return value
    })
  }, [])

  const push = useCallback((raw) => {
    const event = normalizeEvent(raw)
    if (!event) return
    if (seenRef.current.has(event.key)) return
    seenRef.current.add(event.key)

    if (seenRef.current.size > MAX_EVENTS * 3) {
      const trimmed = Array.from(seenRef.current).slice(-MAX_EVENTS * 2)
      seenRef.current = new Set(trimmed)
    }

    if (pausedRef.current) {
      bufferRef.current = [event, ...bufferRef.current].slice(0, MAX_EVENTS)
      setBufferedCount(bufferRef.current.length)
      return
    }

    setEvents((current) => [event, ...current].slice(0, MAX_EVENTS))
  }, [])

  const flushBuffer = useCallback(() => {
    if (pausedRef.current) return
    const buffered = bufferRef.current
    if (!buffered.length) return
    bufferRef.current = []
    setBufferedCount(0)
    setEvents((current) => [...buffered, ...current].slice(0, MAX_EVENTS))
  }, [])

  const clear = useCallback(() => {
    bufferRef.current = []
    setBufferedCount(0)
    setEvents([])
  }, [])

  useEffect(() => {
    if (paused) flushBuffer()
  }, [paused, flushBuffer])

  useEffect(() => {
    if (!enabled) return undefined
    aliveRef.current = true

    const scheduleReconnect = () => {
      if (!aliveRef.current) return
      const attempt = retryRef.current
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** Math.min(attempt, 5))
      retryRef.current = attempt + 1
      setStatus('reconnecting')
      reconnectTimerRef.current = setTimeout(connect, delay)
    }

    function connect() {
      if (!aliveRef.current) return
      setStatus(retryRef.current === 0 ? 'connecting' : 'reconnecting')

      let ws
      try {
        ws = new WebSocket(pipelineWsUrl())
      } catch {
        scheduleReconnect()
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        setStatus('open')
      }

      ws.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data)
          push(data)
        } catch {
          // ignore non-JSON frames
        }
      }

      ws.onerror = () => {
        // onclose will fire
      }

      ws.onclose = () => {
        setStatus('closed')
        if (aliveRef.current) scheduleReconnect()
      }
    }

    connect()

    return () => {
      aliveRef.current = false
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      const ws = wsRef.current
      if (ws) {
        ws.onclose = null
        try { ws.close() } catch { /* noop */ }
      }
      wsRef.current = null
    }
  }, [enabled, push])

  return { events, status, paused, setPaused, togglePause: () => setPaused((p) => !p), clear, bufferedCount }
}
