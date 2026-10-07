const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: JSON_HEADERS,
    ...options,
    headers: { ...JSON_HEADERS, ...(options.headers || {}) },
  })

  const contentType = response.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')
  const body = isJson ? await response.json().catch(() => null) : await response.text().catch(() => '')

  if (!response.ok) {
    const message =
      (isJson && body && (body.detail || body.message)) ||
      (typeof body === 'string' && body) ||
      `Request failed (${response.status})`
    const error = new Error(message)
    error.status = response.status
    error.body = body
    throw error
  }

  return body
}

export const pipelineApi = {
  listEvents({ limit = 100, runId } = {}) {
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    if (runId) params.set('run_id', runId)
    return request(`/api/pipeline/events?${params.toString()}`)
  },

  listRuns({ limit = 100 } = {}) {
    return request(`/api/pipeline/runs?limit=${limit}`)
  },

  approveRun(runId, { by = 'admin' } = {}) {
    return request(`/api/pipeline/runs/${encodeURIComponent(runId)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ by }),
    })
  },

  rejectRun(runId, { by = 'admin', notes } = {}) {
    return request(`/api/pipeline/runs/${encodeURIComponent(runId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ by, notes }),
    })
  },
}

export function pipelineWsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/pipeline/ws`
}
