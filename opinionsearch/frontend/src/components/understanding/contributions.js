import { requestJSON } from './api'

export const contributionDemo = import.meta.env.DEV && import.meta.env.MODE === 'demo'
const contributionIdPattern = /^(?!example-)[A-Za-z0-9_-]{1,128}$/
const BASE = '/api/v1/contributions/'

export async function createContribution(input) {
  const result = contributionDemo
    ? (await import('./contribution-demo')).createDemoContribution(input)
    : await requestJSON(BASE, { method: 'POST', body: { ...input, publication: 'public' }, timeoutMs: 120000 })
  if (typeof result.id !== 'string' || !contributionIdPattern.test(result.id) || result.publication !== (contributionDemo ? 'private' : 'public') || (!contributionDemo && result.searchable !== true) || typeof result.accessToken !== 'string' || !result.accessToken) {
    throw new Error('The server did not return a valid submission receipt.')
  }
  return result
}

export async function getContribution(id, { token, signal } = {}) {
  const result = contributionDemo
    ? (await import('./contribution-demo')).getDemoContribution(id, token)
    : await requestJSON(BASE + encodeURIComponent(id) + '/', { token, signal })
  if (result.id !== id || typeof result.text !== 'string' || !['private', 'public'].includes(result.publication) || (result.publication === 'public' && typeof result.searchable !== 'boolean') || typeof result.createdAt !== 'string' || !Number.isFinite(Date.parse(result.createdAt))) {
    throw new Error('The server did not return a valid contribution.')
  }
  return result
}
