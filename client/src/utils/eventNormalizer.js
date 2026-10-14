export function normalizeEvent(raw) {
  if (!raw || typeof raw !== 'object') return null
  const eventId = raw.event_id || raw.id
  const timestamp = raw.event_time || raw.received_at || null
  const key = eventId
    ? String(eventId)
    : `${raw.event_type || 'event'}:${timestamp || 'now'}:${Math.random().toString(36).slice(2, 8)}`

  return {
    key,
    kind: raw.kind || 'live',
    isHistory: raw.kind === 'history',
    event_type: raw.event_type || 'unknown',
    source: raw.source || 'unknown',
    run_id: raw.run_id || null,
    status: raw.status || null,
    timestamp,
    received_at: raw.received_at || null,
    payload: raw.payload || {},
  }
}