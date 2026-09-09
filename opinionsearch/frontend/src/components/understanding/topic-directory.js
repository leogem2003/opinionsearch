import { EXAMPLE_TOPICS, EXAMPLE_DISCUSSIONS } from './discussion-examples.js'
import { sortDiscussions } from './discussion-sorting.js'

// Provider boundary for a future discussion API. UI examples never enter public counts.
// Discussion records need: id, topicId, title, createdAt, lastContributionAt,
// contributionCount. Topic assignment and aggregation belong to the future pipeline.
export async function loadTopicDirectory(dataset) {
  if (dataset === 'demo') return EXAMPLE_TOPICS.map(topic => ({ ...topic,
    discussions: EXAMPLE_DISCUSSIONS.filter(discussion => discussion.topicId === topic.id),
  }))
  // Public discussion data will get its own backend contract later.
  return []
}

export function directoryView(topics, { query = '', sort } = {}) {
  const match = value => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  return topics.map(topic => ({ ...topic,
    discussions: sortDiscussions(match(topic.title) ? topic.discussions : topic.discussions.filter(item => match(item.title)), sort),
  })).filter(topic => match(topic.title) || topic.discussions.length)
}
