import { useEffect, useId, useState } from 'react'
import { dateLabel } from './api'
import { loadTopicDirectory } from './topic-directory'
import './topic-index.css'

const SORTS = [
  { id: 'popular', label: 'Most opinions', compare: (a, b) => b.opinionCount - a.opinionCount },
  { id: 'recent', label: 'Recently active', compare: (a, b) => (Date.parse(b.lastContributionAt) || 0) - (Date.parse(a.lastContributionAt) || 0) },
  { id: 'title', label: 'Alphabetical', compare: (a, b) => a.title.localeCompare(b.title) },
]

export default function PublicTopicDirectory({ compact = false }) {
  const sortId = useId()
  const [topics, setTopics] = useState(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [sort, setSort] = useState('popular')
  useEffect(() => {
    const controller = new AbortController()
    setError(false)
    loadTopicDirectory('public', { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setTopics(result) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [attempt])
  if (error) return <div className="opinion-search-note"><p role="alert">Topics could not be loaded.</p><button className="civic-text-button" onClick={() => setAttempt(value => value + 1)}>Try again →</button></div>
  if (!topics) return <p className="opinion-search-note" role="status">Loading topics…</p>
  const ordered = [...topics].filter(topic => topic.id !== 'unassigned' || topic.opinionCount > 0).sort((a, b) => SORTS.find(item => item.id === sort).compare(a, b) || a.title.localeCompare(b.title))
  const visible = compact ? ordered.slice(0, 4) : ordered
  return <section className="public-topic-directory" aria-label="Browse opinion topics">
    <header className="public-directory-heading"><h2>Browse by topic</h2>{!compact && <div><label className="civic-sr-only" htmlFor={sortId}>Sort topics</label><select id={sortId} value={sort} onChange={event => setSort(event.target.value)}>{SORTS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div>}</header>
    <ul className="directory-discussions public-topic-list">{visible.map(topic => <li key={topic.id}><a href={`/topics/${encodeURIComponent(topic.id)}`}>
      <div><h3>{topic.title}</h3><p>{topic.opinionCount} opinion{topic.opinionCount === 1 ? '' : 's'}{topic.lastContributionAt && <> <span aria-hidden="true">·</span> Last contribution {dateLabel(topic.lastContributionAt)}</>}</p></div><span aria-hidden="true">→</span>
    </a></li>)}</ul>
    <p className="public-topic-note">An opinion can appear under more than one topic.</p>
  </section>
}
