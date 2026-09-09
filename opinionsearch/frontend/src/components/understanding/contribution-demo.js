// Frontend-only demonstration. These records never reach a backend.
import { submissionKey as randomKey } from './api'
const STORE = 'opinionsearch.demo-contributions.v1'

function records() {
  return JSON.parse(sessionStorage.getItem(STORE) || '{}')
}

export function createDemoContribution({ text, submissionKey }) {
  const all = records()
  const previous = Object.values(all).find(item => item.submissionKey === submissionKey)
  if (previous && previous.text !== text) throw Object.assign(new Error('Submission key already used with different text.'), { status: 409 })
  const saved = previous || { id: 'demo_' + randomKey().slice(0, 32), text, submissionKey, accessToken: randomKey(), createdAt: new Date().toISOString() }
  if (!previous) {
    all[saved.id] = saved
    sessionStorage.setItem(STORE, JSON.stringify(all))
  }
  return { id: saved.id, publication: 'private', accessToken: saved.accessToken }
}

export function getDemoContribution(id, token) {
  const saved = records()[id]
  if (!saved || !token || saved.accessToken !== token) throw Object.assign(new Error('Contribution unavailable.'), { status: 404 })
  return { id: saved.id, text: saved.text, createdAt: saved.createdAt, publication: 'private' }
}
