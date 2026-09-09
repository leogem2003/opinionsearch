// The directory owns presentation order. Later ranking methods can join this registry.
export const DISCUSSION_SORTS = [
  { id: 'recent', label: 'Recently active', field: 'lastContributionAt' },
  { id: 'contributions', label: 'Most contributions', field: 'contributionCount' },
  { id: 'newest', label: 'Newest', field: 'createdAt' },
]

const DEFAULT_DISCUSSION_SORT = 'recent'

export function discussionSort(id) {
  return DISCUSSION_SORTS.find(sort => sort.id === id) || DISCUSSION_SORTS.find(sort => sort.id === DEFAULT_DISCUSSION_SORT)
}

export function sortDiscussions(discussions, sortId) {
  const { field } = discussionSort(sortId)
  return [...discussions].sort((a, b) => (b[field] ?? 0) - (a[field] ?? 0) || a.id.localeCompare(b.id, 'en'))
}
