async function request(path, options = {}) {
  const response = await fetch(path, options)
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map(issue => issue.msg).filter(Boolean).join(', ')
      : typeof detail === 'string'
        ? detail
        : body?.message
    const error = new Error(message || `Request failed (${response.status}).`)
    error.status = response.status
    throw error
  }

  return body
}

export function loginMedicineUser(email, password) {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
}

export function verifyManualEntry(fields, token) {
  return request('/scans/manual', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ fields, gtin: '', serial: '', location: null, method: 'manual' }),
  })
}