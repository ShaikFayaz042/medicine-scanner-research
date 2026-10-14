import { SYSTEM_NODES, SFN_NODES } from './layouts'

const ECS_FAMILY_MAP = {
  'medicine-scanner-scraper': { sys: 'scraper',    sfn: null },
  'data-extractor-task':      { sys: 'extractor',  sfn: 'sfn-extractor'  },
  'data-classifier-task':     { sys: 'classifier', sfn: 'sfn-classifier' },
  'data-processor-task':      { sys: 'processor',  sfn: 'sfn-processor'  },
  'data-ingester-task':       { sys: 'ingestor',   sfn: null },
}

// Which ECS family events belong to which node
const NODE_FAMILIES = {
  scraper:          'medicine-scanner-scraper',
  extractor:        'data-extractor-task',
  classifier:       'data-classifier-task',
  processor:        'data-processor-task',
  ingestor:         'data-ingester-task',
  'sfn-extractor':  'data-extractor-task',
  'sfn-classifier': 'data-classifier-task',
  'sfn-processor':  'data-processor-task',
}

const SFN_NODE_IDS = new Set(['sfn', 'sfn-start', 'sfn-check', 'sfn-success', 'sfn-failed', 'sfn-end'])

function parseSfnInput(input) {
  if (!input) return null
  try {
    const parsed = typeof input === 'string' ? JSON.parse(input) : input
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export function deriveGraphState(events) {
  const empty = { nodeStates: {}, activeEdges: [], runId: null }
  if (!events || !events.length) return empty

  const latestRunId = events.find((e) => e.run_id)?.run_id
  if (!latestRunId) return empty

  const runEvents = events
    .filter((e) => e.run_id === latestRunId)
    .slice()
    .reverse()

  const nodeStates = {}

  for (const evt of runEvents) {
    if (evt.event_type === 'sfn.state_change') {
      const detail = evt.payload?.detail || {}
      const status = detail.status || evt.status

      if (status === 'RUNNING') {
        nodeStates['sfn'] = 'running'
        nodeStates['sfn-start'] = 'success'
        nodeStates['sfn-check'] = 'running'

        const input = parseSfnInput(detail.input)
        if (input && input.has_pdfs === false) {
          nodeStates['sfn-extractor'] = 'skipped'
          nodeStates['extractor'] = 'skipped'
        }
      } else if (status === 'SUCCEEDED') {
        nodeStates['sfn'] = 'success'
        nodeStates['sfn-check'] = 'success'
        nodeStates['sfn-processor'] = 'success'
        nodeStates['sfn-success'] = 'success'
        nodeStates['sfn-end'] = 'success'
        nodeStates['processor'] = 'success'
      } else if (['FAILED', 'TIMED_OUT', 'ABORTED'].includes(status)) {
        nodeStates['sfn'] = 'failed'
        nodeStates['sfn-failed'] = 'failed'
        nodeStates['sfn-end'] = 'success'
      }
    }

    if (evt.event_type === 'ecs.task_state_change') {
      const detail = evt.payload?.detail || {}
      const family = String(detail.group || '').replace('family:', '')
      const map = ECS_FAMILY_MAP[family]
      if (!map) continue

      const lastStatus = detail.lastStatus
      const container = Array.isArray(detail.containers) ? detail.containers[0] : null
      const exitCode = container?.exitCode
      const stopCode = detail.stopCode

      if (lastStatus === 'RUNNING') {
        nodeStates[map.sys] = 'running'
        if (map.sfn) nodeStates[map.sfn] = 'running'

        if (family === 'medicine-scanner-scraper') {
          nodeStates['scheduler'] = 'success'
          nodeStates['source-queue'] = 'running'
          for (let index = 1; index <= 5; index += 1) {
            nodeStates[`data-source-${index}`] = 'running'
          }
        } else if (family === 'data-ingester-task') {
          nodeStates['meddb'] = 'running'
          nodeStates['scraperdb2'] = 'running'
        }
      } else if (lastStatus === 'STOPPED') {
        const ok = stopCode === 'EssentialContainerExited' && exitCode === 0
        const finalState = ok ? 'success' : 'failed'
        nodeStates[map.sys] = finalState
        if (map.sfn) nodeStates[map.sfn] = finalState
        if (family === 'medicine-scanner-scraper') {
          nodeStates['source-queue'] = finalState
          for (let index = 1; index <= 5; index += 1) {
            nodeStates[`data-source-${index}`] = finalState
          }
          nodeStates['s3'] = finalState
          nodeStates['scraperdb'] = finalState
        } else if (family === 'data-ingester-task') {
          nodeStates['meddb'] = finalState
          nodeStates['scraperdb2'] = finalState
        }
      }
    }
  }

  const activeEdges = []
  const rule = (id, src, tgt) => {
    const s = nodeStates[src]
    const t = nodeStates[tgt]
    if (t === 'running') return activeEdges.push(id)
    if (s === 'success' && t && t !== 'idle') return activeEdges.push(id)
  }

  rule('e-sch-scr',  'scheduler',  'scraper')
  if (nodeStates.scraper === 'running') {
    activeEdges.push(
      'e-source-1-queue', 'e-source-2-queue', 'e-source-3-queue', 'e-source-4-queue', 'e-source-5-queue',
      'e-queue-scraper', 'e-scr-s3', 'e-scr-db'
    )
  }
  rule('e-s3-sfn',   's3',         'sfn')
  rule('e-sfn-ext',  'sfn',        'extractor')
  rule('e-sfn-cls',  'sfn',        'classifier')
  rule('e-sfn-prc',  'sfn',        'processor')
  rule('e-ext-ing',  'extractor',  'ingestor')
  rule('e-cls-ing',  'classifier', 'ingestor')
  rule('e-prc-ing',  'processor',  'ingestor')
  rule('e-ing-med',  'ingestor',   'meddb')
  rule('e-ing-scdb', 'ingestor',   'scraperdb2')

  rule('s1',  'sfn-start',      'sfn-check')
  rule('s2',  'sfn-check',      'sfn-extractor')
  rule('s3',  'sfn-check',      'sfn-classifier')
  rule('s5',  'sfn-extractor',  'sfn-processor')
  rule('s6',  'sfn-classifier', 'sfn-processor')
  rule('s7',  'sfn-processor',  'sfn-success')
  rule('s9',  'sfn-success',    'sfn-end')

  return { nodeStates, activeEdges, runId: latestRunId }
}

/** Summarize ECS and Step Functions lifecycle events for one run. */
export function getStageSnapshot(events, runId) {
  const snapshot = {
    scraperState: 'idle',
    sfnState: 'idle',
    extractorState: 'idle',
    classifierState: 'idle',
    processorState: 'idle',
    ingestorState: 'idle',
    scraperExit: null,
    sfnStatus: null,
  }
  const stateByFamily = {
    'medicine-scanner-scraper': 'scraperState',
    'data-extractor-task': 'extractorState',
    'data-classifier-task': 'classifierState',
    'data-processor-task': 'processorState',
    'data-ingester-task': 'ingestorState',
  }
  const scopedEvents = (events || [])
    .filter((event) => event.run_id === runId)
    .slice()
    .sort((left, right) => new Date(left.timestamp || left.event_time || 0) - new Date(right.timestamp || right.event_time || 0))

  for (const event of scopedEvents) {
    const detail = event.payload?.detail || {}
    if (event.event_type === 'sfn.state_change') {
      const status = detail.status || event.status
      snapshot.sfnStatus = status || snapshot.sfnStatus
      if (status === 'RUNNING') snapshot.sfnState = 'running'
      if (status === 'SUCCEEDED') snapshot.sfnState = 'success'
      if (['FAILED', 'TIMED_OUT', 'ABORTED'].includes(status)) snapshot.sfnState = 'failed'
    }
    if (event.event_type !== 'ecs.task_state_change') continue

    const family = String(detail.group || '').replace('family:', '')
    const stateKey = stateByFamily[family]
    if (!stateKey) continue
    if (detail.lastStatus === 'RUNNING') snapshot[stateKey] = 'running'
    if (detail.lastStatus === 'STOPPED') {
      const container = Array.isArray(detail.containers) ? detail.containers[0] : null
      const exitCode = container?.exitCode
      snapshot[stateKey] = exitCode === 0 ? 'success' : 'failed'
      if (stateKey === 'scraperState') snapshot.scraperExit = Number.isInteger(exitCode) ? exitCode : null
    }
  }
  return snapshot
}

/** Filter events scoped to a specific node. */
export function filterEventsForNode(nodeId, events) {
  if (!events || !events.length) return []

  if (SFN_NODE_IDS.has(nodeId)) {
    return events.filter((e) => e.source === 'aws.states' || e.payload?.source === 'aws.states')
  }

  const family = NODE_FAMILIES[nodeId]
  if (family) {
    return events.filter((e) => {
      const group = e.payload?.detail?.group || ''
      return group === `family:${family}`
    })
  }

  // scheduler, data sources, source queue, s3, scraperdb, meddb, scraperdb2 — no direct events
  return []
}

// Static lookup of node metadata across both graphs
const ALL_NODES_BY_ID = (() => {
  const map = {}
  for (const n of SYSTEM_NODES) map[n.id] = n
  for (const n of SFN_NODES) map[n.id] = n
  return map
})()

export function findNodeMeta(nodeId) {
  return ALL_NODES_BY_ID[nodeId] || null
}