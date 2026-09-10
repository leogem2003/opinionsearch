import { EXAMPLE_TOPICS, EXAMPLE_DISCUSSIONS } from './discussion-examples.js'
import { sortDiscussions } from './discussion-sorting.js'
import { requestJSON } from './api.js'

// The public catalogue comes from stored backend assignments. Examples remain
// a separate provider with nested discussions and never enter public counts.
export async function loadTopicDirectory(dataset, { signal } = {}) {
  if (dataset === 'demo') return EXAMPLE_TOPICS.map(topic => ({ ...topic,
    discussions: EXAMPLE_DISCUSSIONS.filter(discussion => discussion.topicId === topic.id),
  }))
  const result = await requestJSON('/api/v1/topics/', { signal })
  if (!Array.isArray(result.topics) || result.topics.some(topic => typeof topic.id !== 'string' || typeof topic.title !== 'string' || !Number.isInteger(topic.opinionCount))) throw new Error('Invalid topic directory')
  return result.topics
}

export function directoryView(topics, { query = '', sort } = {}) {
  const match = value => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  return topics.map(topic => ({ ...topic,
    discussions: sortDiscussions(match(topic.title) ? topic.discussions : topic.discussions.filter(item => match(item.title)), sort),
  })).filter(topic => match(topic.title) || topic.discussions.length)
}
