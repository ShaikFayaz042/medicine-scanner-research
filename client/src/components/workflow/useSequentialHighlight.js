import { useEffect, useMemo, useState } from 'react'

const SOURCE_ALIASES = {
  'data-source-1': ['cdsco alerts', 'cdsco-alerts', 'cdsco_alerts'],
  'data-source-2': ['cdsco fdc', 'cdsco-fdc', 'cdsco_fdc'],
  'data-source-3': ['banned drugs', 'cdsco-banned', 'cdsco_banned'],
  'data-source-4': ['ipc pvpi', 'ipc-pvpi', 'ipc_pvpi'],
  'data-source-5': ['cdsco nsq', 'cdsco-nsq', 'cdsco_nsq'],
}

/** Convert source labels and source keys to a comparable token. */
function sourceToken(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** Highlight manifest-confirmed sources or cycle through sources while scraping. */
export function useSequentialHighlight({ sources, manifest, scraperState }) {
  const sourceIds = sources.map((source) => typeof source === 'string' ? source : source.id)
  const hasManifest = Array.isArray(manifest?.sources)
  const manifestSources = new Set((manifest?.sources || []).map(sourceToken))
  const manifestSourceIds = sourceIds.filter((sourceId) => {
    const aliases = SOURCE_ALIASES[sourceId] || [sourceId]
    const source = sources.find((item) => (typeof item === 'string' ? item : item.id) === sourceId)
    const label = typeof source === 'string' ? source : source?.data?.label
    return [...aliases, label].some((alias) => manifestSources.has(sourceToken(alias)))
  })
  const cycleIds = hasManifest ? manifestSourceIds : sourceIds
  const cycleKey = `${cycleIds.join(',')}:${hasManifest ? 'manifest' : scraperState}`
  const [cycle, setCycle] = useState({ key: '', index: 0 })
  const cycleIndex = cycle.key === cycleKey ? cycle.index : 0
  const shouldCycle = cycleIds.length > 0 && (hasManifest
    ? cycleIndex < cycleIds.length
    : scraperState === 'running')
  const activeIndex = shouldCycle ? sourceIds.indexOf(cycleIds[cycleIndex]) : -1

  useEffect(() => {
    if (!shouldCycle) return undefined
    const delay = hasManifest ? 2000 : 1500
    const timer = setInterval(() => {
      setCycle((current) => {
        const index = current.key === cycleKey ? current.index : 0
        return {
          key: cycleKey,
          index: hasManifest ? Math.min(index + 1, cycleIds.length) : (index + 1) % cycleIds.length,
        }
      })
    }, delay)
    return () => clearInterval(timer)
  }, [cycleIds.length, cycleKey, hasManifest, shouldCycle])

  const statusById = useMemo(() => {
    const statuses = Object.fromEntries(sourceIds.map((sourceId) => [sourceId, 'idle']))
    if (hasManifest) {
      const currentIndex = cycle.key === cycleKey ? cycle.index : 0
      manifestSourceIds.forEach((sourceId, index) => {
        statuses[sourceId] = currentIndex >= manifestSourceIds.length || index < currentIndex
          ? 'success'
          : index === currentIndex ? 'running' : 'idle'
      })
    } else if (scraperState === 'running' && activeIndex >= 0) {
      statuses[sourceIds[activeIndex]] = 'running'
    }
    return statuses
  }, [activeIndex, cycle, cycleKey, hasManifest, manifestSourceIds, scraperState, sourceIds])

  return { activeIndex, statusById }
}