import { useCallback, useEffect, useState } from 'react'

/** Fetch one run-scoped artifact, retrying temporary 404 responses. */
function useRunArtifact({ runId, enabled, path }) {
  const requestKey = `${runId || ''}:${path}`
  const [result, setResult] = useState({ key: '', data: null, loading: false, error: null })

  const refetch = useCallback(async (signal) => {
    if (!runId || !enabled) return null
    setResult({ key: requestKey, data: null, loading: true, error: null })
    try {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const response = await fetch(`/api/pipeline/runs/${encodeURIComponent(runId)}/${path}`, { signal })
        if (response.status === 404 && attempt < 2) {
          await new Promise((resolve, reject) => {
            const timer = setTimeout(resolve, 3000)
            signal?.addEventListener('abort', () => {
              clearTimeout(timer)
              reject(new DOMException('Request aborted', 'AbortError'))
            }, { once: true })
          })
          continue
        }
        if (!response.ok) throw new Error(`Artifact request failed (${response.status})`)
        const result = await response.json()
        setResult({ key: requestKey, data: result, loading: false, error: null })
        return result
      }
      throw new Error('Artifact not found after 3 attempts')
    } catch (requestError) {
      if (requestError.name !== 'AbortError') {
        setResult({ key: requestKey, data: null, loading: false, error: requestError.message })
      }
      return null
    } finally {
      setResult((current) => current.key === requestKey ? { ...current, loading: false } : current)
    }
  }, [enabled, path, requestKey, runId])

  useEffect(() => {
    if (!enabled || !runId) return undefined
    const controller = new AbortController()
    queueMicrotask(() => {
      if (!controller.signal.aborted) refetch(controller.signal)
    })
    return () => controller.abort()
  }, [enabled, refetch, runId])

  const current = result.key === requestKey ? result : { data: null, loading: false, error: null }
  return { ...current, refetch: () => refetch() }
}

/** Fetch the current run's manifest after scraper completion. */
export function useManifest({ runId, enabled }) {
  const result = useRunArtifact({ runId, enabled, path: 'manifest' })
  return { manifest: result.data, loading: result.loading, error: result.error, refetch: result.refetch }
}

/** Fetch normalized artifact counts after the workflow succeeds. */
export function useNormalized({ runId, enabled }) {
  const result = useRunArtifact({ runId, enabled, path: 'artifacts/normalized' })
  return { data: result.data, loading: result.loading, error: result.error, refetch: result.refetch }
}