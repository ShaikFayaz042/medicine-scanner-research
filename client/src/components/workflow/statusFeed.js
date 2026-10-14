import { getStageSnapshot } from './stateMapper'

/** Return the event's most useful timestamp as an ISO string. */
function eventAt(event) {
  const value = event?.timestamp || event?.event_time || event?.received_at
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

/** Select the newest matching ECS lifecycle event for a task family. */
function latestTaskEvent(events, family) {
  return events
    .filter((event) => event.event_type === 'ecs.task_state_change'
      && String(event.payload?.detail?.group || '').replace('family:', '') === family)
    .slice()
    .sort((left, right) => new Date(eventAt(left) || 0) - new Date(eventAt(right) || 0))
    .at(-1) || null
}

/** Map a task snapshot state to its feed tone and timestamp. */
function taskFeedState(state, event) {
  if (state === 'running') return { tone: 'running', at: eventAt(event) }
  if (state === 'success') return { tone: 'success', at: eventAt(event) }
  if (state === 'failed') return { tone: 'failed', at: eventAt(event) }
  return { tone: 'idle', at: null }
}

/** Derive ordered user-facing workflow milestones from events and fetched artifacts. */
export function deriveStatusFeed({ events = [], runId, manifest, normalized, triggeredAt }) {
  const runEvents = (events || []).filter((event) => runId && event.run_id === runId)
  const snapshot = getStageSnapshot(runEvents, runId)
  const scraperEvent = latestTaskEvent(runEvents, 'medicine-scanner-scraper')
  const scraperStartEvent = runEvents
    .filter((event) => event.event_type === 'ecs.task_state_change'
      && event.payload?.detail?.group === 'family:medicine-scanner-scraper'
      && event.payload?.detail?.lastStatus === 'RUNNING')
    .slice()
    .sort((left, right) => new Date(eventAt(left) || 0) - new Date(eventAt(right) || 0))
    .at(-1) || null
  const scraperStopEvent = runEvents
    .filter((event) => event.event_type === 'ecs.task_state_change'
      && event.payload?.detail?.group === 'family:medicine-scanner-scraper'
      && event.payload?.detail?.lastStatus === 'STOPPED')
    .slice()
    .sort((left, right) => new Date(eventAt(left) || 0) - new Date(eventAt(right) || 0))
    .at(-1) || null
  const extractorEvent = latestTaskEvent(runEvents, 'data-extractor-task')
  const classifierEvent = latestTaskEvent(runEvents, 'data-classifier-task')
  const processorEvent = latestTaskEvent(runEvents, 'data-processor-task')
  const sfnEvent = runEvents
    .filter((event) => event.event_type === 'sfn.state_change')
    .slice()
    .sort((left, right) => new Date(eventAt(left) || 0) - new Date(eventAt(right) || 0))
    .at(-1) || null
  const feed = []
  /** Append one milestone to the ordered feed. */
  const add = (key, label, tone, at = null) => feed.push({ key, label, tone, at })
  /** Append idle placeholders for milestones not reached after a failure. */
  const addIdleTail = (steps) => steps.forEach(([key, label]) => add(key, label, 'idle'))

  if (triggeredAt) add('trigger', 'Triggering scraper', 'success', triggeredAt)
  if (scraperStartEvent) add('scraper-start', 'Scraper started', 'success', eventAt(scraperStartEvent))

  const scraperStartedAt = eventAt(scraperStartEvent)
  const scraperElapsed = scraperStartedAt ? Date.now() - new Date(scraperStartedAt).getTime() : 0
  const scraperStopped = Boolean(scraperStopEvent)
  const sourceScanReached = manifest || scraperStopped || (snapshot.scraperState === 'running' && scraperElapsed > 3000)
  if (sourceScanReached) {
    const scanTone = scraperStopped || manifest ? 'success' : 'running'
    add('finding-sources', 'Finding docs in sources', scanTone, manifest?.triggered_at || (scraperStopped ? eventAt(scraperStopEvent) : scraperStartedAt))
  }

  const manifestCount = manifest?.documents_count
  if (manifest && manifestCount > 0) {
    add('found-documents', `Found ${manifestCount} new docs`, 'success', manifest.triggered_at || eventAt(scraperEvent))
  } else if (!manifest && (snapshot.scraperState === 'running' || scraperStopped)) {
    add('finding-documents', 'Finding documents…', 'running', scraperStartedAt)
  }

  if (scraperStopped) {
    add('scraping-end', 'Scraping end', 'success', eventAt(scraperStopEvent))
    if (snapshot.scraperState === 'success') {
      add('documents-saved', 'Docs saved in DB and S3', 'success', eventAt(scraperStopEvent))
    } else {
      add('documents-saved', 'Docs saved in DB and S3', 'idle')
      add('scraper-failed', `Scraper failed: ${scraperEvent?.payload?.detail?.stopCode || (snapshot.scraperExit ?? 'unknown')}`, 'failed', eventAt(scraperEvent))
      addIdleTail([
        ['orchestrator', 'Pipeline started'], ['extracting', 'Extracting docs'],
        ['classifying', 'Classifying docs'], ['processing', 'Processing docs'],
        ['processing-completed', 'Processing completed'], ['normalized', 'Normalized records'],
        ['workflow-completed', 'Workflow completed'], ['approval', 'Waiting for approval'],
      ])
      return feed
    }
  }

  if (snapshot.sfnState !== 'idle') {
    add('orchestrator', 'Pipeline started', 'success', eventAt(sfnEvent))
  }

  if (snapshot.sfnState === 'failed') {
    const extracting = taskFeedState(snapshot.extractorState, extractorEvent)
    add('extracting', 'Extracting docs', extracting.tone, extracting.at)
    add('workflow-failed', 'Workflow failed', 'failed', eventAt(sfnEvent))
    addIdleTail([
      ['classifying', 'Classifying docs'], ['processing', 'Processing docs'],
      ['processing-completed', 'Processing completed'], ['normalized', 'Normalized records'],
      ['workflow-completed', 'Workflow completed'], ['approval', 'Waiting for approval'],
    ])
    return feed
  }

  const processingSteps = [
    ['extracting', 'Extracting docs', snapshot.extractorState, extractorEvent],
    ['classifying', 'Classifying docs', snapshot.classifierState, classifierEvent],
    ['processing', 'Processing docs', snapshot.processorState, processorEvent],
  ]
  for (const [key, label, state, taskEvent] of processingSteps) {
    const reached = state !== 'idle' || snapshot.sfnState === 'failed'
    if (reached) {
      const status = taskFeedState(state, taskEvent)
      add(key, label, status.tone, status.at)
    }
  }

  if (snapshot.processorState === 'success') {
    add('processing-completed', `Processing completed for ${manifestCount > 0 ? manifestCount : 'all docs'}`, 'success', eventAt(processorEvent))
  }
  if (normalized && normalized.file_count > 0) {
    add('normalized', `Normalized ${normalized.record_count} records`, 'success', eventAt(sfnEvent))
  }

  if (snapshot.sfnState === 'success') {
    add('workflow-completed', 'Workflow completed', 'success', eventAt(sfnEvent))
    const ingestorReached = runEvents.some((event) => event.event_type === 'ecs.task_state_change'
      && String(event.payload?.detail?.group || '').replace('family:', '') === 'data-ingester-task')
    add('approval', 'Waiting for approval', ingestorReached ? 'success' : 'running', ingestorReached ? eventAt(latestTaskEvent(runEvents, 'data-ingester-task')) : eventAt(sfnEvent))
  }
  return feed
}