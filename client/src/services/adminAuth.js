const ADMIN_SESSION_KEY = 'medicine-scanner-admin-session'

export function clearAdminSession() {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(ADMIN_SESSION_KEY)
  }
}

export function getAdminSession() {
  if (typeof window === 'undefined') return null

  try {
    const session = JSON.parse(window.localStorage.getItem(ADMIN_SESSION_KEY) || 'null')
    if (!session?.token || !session.expiresAt || session.expiresAt <= Date.now()) {
      window.localStorage.removeItem(ADMIN_SESSION_KEY)
      return null
    }
    return session
  } catch {
    window.localStorage.removeItem(ADMIN_SESSION_KEY)
    return null
  }
}

export function storeAdminSession(authResponse) {
  const expiresIn = authResponse.expiresIn ?? authResponse.expires_in
  const session = {
    token: authResponse.token,
    expiresAt: Date.now() + expiresIn * 1000,
    user: authResponse.user,
  }
  window.localStorage.setItem(ADMIN_SESSION_KEY, JSON.stringify(session))
  return session
}

export async function loginAdmin(email, password) {
  const response = await fetch('/api/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email.trim(), password }),
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const error = new Error(body?.detail || `Sign in failed (${response.status}).`)
    error.status = response.status
    throw error
  }

  if (!body?.token || !(body.expiresIn ?? body.expires_in)) {
    throw new Error('The server returned an incomplete sign-in response.')
  }

  return storeAdminSession(body)
}

export function adminFetch(path, options = {}) {
  const session = getAdminSession()
  const headers = new Headers(options.headers || {})
  if (session?.token) headers.set('Authorization', `Bearer ${session.token}`)
  return fetch(path, { ...options, headers })
}