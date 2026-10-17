// Small fetch wrapper for the CRM API.
// - sends the session cookie (same origin)
// - adds the CSRF token on every write
// - turns problem+json errors into ApiError objects

let csrfToken = null

export function setCsrfToken(token) {
  csrfToken = token
}

export class ApiError extends Error {
  constructor(status, problem) {
    super(problem?.detail || problem?.title || `Request failed (${status})`)
    this.status = status
    this.problem = problem || {}
    this.type = problem?.type || 'about:blank'
    this.title = problem?.title || 'Something went wrong'
    this.fieldErrors = problem?.errors || []
  }

  is(slug) {
    return this.type === `urn:crm:problem:${slug}`
  }
}

const listeners = new Set()
// Lets the app react globally to "logged out" (401) responses.
export function onUnauthorized(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export async function api(path, { method = 'GET', body, form, headers = {} } = {}) {
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json', ...headers } }
  if (form !== undefined) {
    init.body = form // FormData: the browser sets the multipart Content-Type itself
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  if (method !== 'GET' && csrfToken) {
    init.headers['X-CSRF-Token'] = csrfToken
  }

  let response
  try {
    response = await fetch(`/api/v1${path}`, init)
  } catch {
    throw new ApiError(0, { title: 'Cannot reach the server', detail: 'Check your connection and try again.' })
  }

  if (response.status === 204) return null
  const isJson = (response.headers.get('content-type') || '').includes('json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    const error = new ApiError(response.status, data)
    if (response.status === 401 && error.is('not-authenticated')) {
      listeners.forEach((fn) => fn())
    }
    throw error
  }
  return data
}
