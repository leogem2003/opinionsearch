const RECEIPTS_KEY = `opinionsearch.contribution-receipts.v1:${import.meta.env.MODE}`

export function saveReceipt(receipt) {
  try {
    const receipts = JSON.parse(sessionStorage.getItem(RECEIPTS_KEY) || '{}')
    receipts[receipt.id] = receipt.accessToken
    sessionStorage.setItem(RECEIPTS_KEY, JSON.stringify(Object.fromEntries(Object.entries(receipts).slice(-30))))
    return true
  } catch { return false }
}

export function receiptToken(id) {
  const receipt = window.history.state?.opinionsearchReceipt
  const fallback = receipt?.id === id ? receipt.accessToken : null
  try { return JSON.parse(sessionStorage.getItem(RECEIPTS_KEY) || '{}')[id] || fallback } catch { return fallback }
}

export function submissionKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('')
}

export async function requestJSON(url, { token, body, method = 'GET', signal } = {}) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timeout = setTimeout(abort, 20000)
  try {
    const response = await fetch(url, {
      method, signal: controller.signal,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const error = new Error(data.error?.message || (typeof data.detail === 'string' ? data.detail : 'Something went wrong. Please try again.'))
      error.status = response.status
      throw error
    }
    return data
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
  }
}

export const stanceLabels = { supports: 'In favour', opposes: 'Not in favour', mixed: 'Mixed / conditional', unclear: 'No clear overall position' }

export function topicIndexURL(dataset = 'public', topicId) {
  const params = new URLSearchParams()
  if (dataset === 'demo') params.set('dataset', 'demo')
  if (topicId) params.set('topic', topicId)
  return '/topics' + (params.size ? '?' + params : '')
}

export function discussionURL(id, dataset = 'public') {
  return `/discussions/${encodeURIComponent(id)}${dataset === 'demo' ? '?dataset=demo' : ''}`
}

export function issueTextError(text) {
  if (!text.trim()) return 'Describe an issue before sending.'
  return [...text.trim()].length > 2000 ? 'Use 2,000 characters or fewer. Your text is still here.' : ''
}

export function discussionReturnURL(id, dataset = 'public') {
  return explorationReturnURL(discussionURL(id, dataset), dataset)
}

function explorationReturnURL(fallback, dataset) {
  const returnTo = new URLSearchParams(window.location.search).get('returnTo')
  if (!returnTo) return fallback
  try {
    const url = new URL(returnTo, window.location.origin)
    const returnedDataset = url.searchParams.get('dataset') === 'demo' ? 'demo' : 'public'
    return url.origin === window.location.origin && url.pathname === new URL(fallback, window.location.origin).pathname && returnedDataset === dataset
      ? url.pathname + url.search + url.hash : fallback
  } catch { return fallback }
}

export function dateLabel(timestamp) {
  return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(typeof timestamp === 'number' ? timestamp * 1000 : timestamp))
}
