/**
 * Minimal fetch wrapper. Every request is a relative `/api` URL with cookie
 * credentials; there is deliberately no base-URL setting and no mock fallback.
 */

const API_PREFIX = '/api'

/** Fired on window when a non-auth request gets 401, i.e. the session expired. */
export const SESSION_EXPIRED_EVENT = 'newton:session-expired'

/** Error raised for any non-2xx response or transport failure. */
export class ApiError extends Error {
  /** HTTP status, or 0 when the server could not be reached at all. */
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

/** Turns FastAPI `{detail}` (string or 422 list) into one readable sentence. */
export function humanizeDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationItem[]).map((item) => {
      const field = (item.loc ?? []).filter((p) => p !== 'body' && p !== 'query').join('.')
      const msg = item.msg ?? 'is invalid'
      return field ? `${field}: ${msg}` : msg
    })
    if (parts.length) return parts.join('; ')
  }
  return `Request failed (HTTP ${status}).`
}

/**
 * Accepts only same-origin `/api/...` URLs. Evidence URLs come from the server,
 * so they are checked before being used in `src`, `href` or `fetch`.
 */
export function safeApiUrl(url: string | null | undefined): string | null {
  if (!url) return null
  return url.startsWith(`${API_PREFIX}/`) && !url.startsWith('//') ? url : null
}

/** Builds an `/api` URL from a contract path such as `/machines/{id}`. */
export function apiUrl(path: string): string {
  return `${API_PREFIX}${path}`
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: unknown
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    detail = undefined
  }
  return new ApiError(response.status, humanizeDetail(detail, response.status))
}

/** Performs a request against an absolute `/api/...` URL and parses JSON. */
export async function requestUrl<T>(url: string, init: RequestInit = {}): Promise<T> {
  if (!safeApiUrl(url)) throw new ApiError(0, 'Refused a non-/api URL.')
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError(0, 'The Newton server could not be reached. Is the backend running?')
  }
  if (response.status === 401 && !url.startsWith(`${API_PREFIX}/auth/`)) {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
  if (!response.ok) throw await parseError(response)
  return (await response.json()) as T
}

export function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestUrl<T>(apiUrl(path), { signal })
}

export function sendJson<T>(method: 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  return requestUrl<T>(apiUrl(path), {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function sendForm<T>(path: string, form: FormData): Promise<T> {
  // The browser sets the multipart boundary; do not set Content-Type here.
  return requestUrl<T>(apiUrl(path), { method: 'POST', body: form })
}

export function del<T>(path: string): Promise<T> {
  return requestUrl<T>(apiUrl(path), { method: 'DELETE' })
}

/** Readable message for anything thrown by the helpers above. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Unexpected error.'
}
