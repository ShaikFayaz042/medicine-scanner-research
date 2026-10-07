import { useCallback, useEffect, useMemo, useState } from 'react'
import { pipelineApi } from '../pipelineApi'
import { normalizeEvent } from '../eventNormalizer'
import { deriveGraphState } from './stateMapper'

export function usePipelineGraphState(socket) {
  const { events: liveEvents, status } = socket

  const [pinnedRunId, setPinnedRunId] = useState(null)
  const [pinnedRunEvents, setPinnedRunEvents] = useState(null)
  const [pinnedRunLoading, setPinnedRunLoading] = useState(false)
  const [scrubIndex, setScrubIndexRaw] = useState(null) // null = live
  const [playing, setPlaying] = useState(false)
  const [resetAt, setResetAt] = useState(0)

  const liveRunId = useMemo(
    () => liveEvents.find((e) => e.run_id)?.run_id || null,
    [liveEvents]
  )

  const effectiveRunId = pinnedRunId || liveRunId

  // Fetch historical events when pinning a non-live run
  useEffect(() => {
    if (!pinnedRunId) { setPinnedRunEvents(null); return undefined }
    if (pinnedRunId === liveRunId) { setPinnedRunEvents(null); return undefined }

    let cancelled = false
    setPinnedRunLoading(true)
    pipelineApi.listEvents({ runId: pinnedRunId, limit: 500 })
      .then((rows) => {
        if (cancelled) return
        const normalized = (Array.isArray(rows) ? rows : [])
          .map((raw) => normalizeEvent({ ...raw, event_id: raw.id, kind: 'history' }))
          .filter(Boolean)
        setPinnedRunEvents(normalized)
      })
      .catch(() => { if (!cancelled) setPinnedRunEvents([]) })
      .finally(() => { if (!cancelled) setPinnedRunLoading(false) })

    return () => { cancelled = true }
  }, [pinnedRunId, liveRunId])

  // Source events for the current view
  const sourceEvents = useMemo(() => {
    if (pinnedRunEvents) return pinnedRunEvents
    if (pinnedRunId && pinnedRunId === liveRunId) {
      return liveEvents.filter((e) => e.run_id === pinnedRunId)
    }
    if (pinnedRunId && pinnedRunId !== liveRunId) return []
    return liveEvents
  }, [liveEvents, pinnedRunId, pinnedRunEvents, liveRunId])

  // Oldest-first for slider
  const runEventsOldestFirst = useMemo(() => {
    return [...sourceEvents].sort(
      (a, b) => new Date(a.timestamp || 0).getTime() - new Date(b.timestamp || 0).getTime()
    )
  }, [sourceEvents])

  const totalEvents = runEventsOldestFirst.length
  const oldestAt = totalEvents ? runEventsOldestFirst[0].timestamp : null
  const newestAt = totalEvents ? runEventsOldestFirst[totalEvents - 1].timestamp : null

  // Reset scrubber on run change
  useEffect(() => {
    setScrubIndexRaw(null)
    setPlaying(false)
  }, [pinnedRunId, liveRunId])

  // If total shrinks below scrub point, jump to live
  useEffect(() => {
    if (scrubIndex !== null && scrubIndex >= totalEvents) setScrubIndexRaw(null)
  }, [totalEvents, scrubIndex])

  // Auto-play ticker
  useEffect(() => {
    if (!playing) return undefined
    if (scrubIndex === null) return undefined
    if (scrubIndex >= totalEvents - 1) {
      setPlaying(false)
      setScrubIndexRaw(null)
      return undefined
    }
    const id = setTimeout(() => {
      setScrubIndexRaw((i) => (i === null ? 0 : i + 1))
    }, 700)
    return () => clearTimeout(id)
  }, [playing, scrubIndex, totalEvents])

  // Visible subset for graph derivation
  const visibleNewestFirst = useMemo(() => {
    if (Date.now() - resetAt < 200) return []
    if (scrubIndex === null) return sourceEvents
    return runEventsOldestFirst.slice(0, scrubIndex + 1).reverse()
  }, [sourceEvents, runEventsOldestFirst, scrubIndex, resetAt])

  const state = useMemo(() => {
    if (!visibleNewestFirst.length) return { nodeStates: {}, activeEdges: [], runId: null }
    return deriveGraphState(visibleNewestFirst)
  }, [visibleNewestFirst])

  const setScrubIndex = useCallback((i) => {
    setPlaying(false)
    setScrubIndexRaw(i)
  }, [])

  const reset = useCallback(() => {
    setResetAt(Date.now())
    setPinnedRunId(null)
    setPinnedRunEvents(null)
    setScrubIndexRaw(null)
    setPlaying(false)
  }, [])

  const pinRun = useCallback((runId) => {
    setPinnedRunId(runId)
    setScrubIndexRaw(null)
    setPlaying(false)
  }, [])

  const unpin = useCallback(() => {
    setPinnedRunId(null)
    setPinnedRunEvents(null)
    setScrubIndexRaw(null)
    setPlaying(false)
  }, [])

  const togglePlay = useCallback(() => {
    setPlaying((p) => {
      const next = !p
      if (next && scrubIndex === null) setScrubIndexRaw(0)
      return next
    })
  }, [scrubIndex])

  return {
    ...state,
    runId: effectiveRunId,
    socketStatus: status,
    pinnedRunId,
    liveRunId,
    pinnedRunLoading,
    pinRun,
    unpin,
    reset,
    // scrubber
    totalEvents,
    scrubIndex,
    setScrubIndex,
    playing,
    togglePlay,
    oldestAt,
    newestAt,
    // for drawer
    events: sourceEvents,
  }
}