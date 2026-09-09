import { useEffect, useState } from 'react'
import { CivicPage } from '../LandingPage'
import { dateLabel, discussionURL } from './api'
import { DISCUSSION_SORTS, discussionSort } from './discussion-sorting'
import { directoryView, loadTopicDirectory } from './topic-directory'
import './understanding.css'
import './exploration.css'
import './topic-index.css'

export default function TopicIndexPage() {
  const initial = new URLSearchParams(window.location.search)
  const [dataset, setDataset] = useState(() => initial.get('dataset') === 'demo' ? 'demo' : 'public')
  const [sort, setSort] = useState(() => discussionSort(initial.get('sort')).id)
  const [query, setQuery] = useState(() => initial.get('q') || '')
  const [topics, setTopics] = useState([])
  const [status, setStatus] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const [closed, setClosed] = useState(() => new Set())
  const visible = directoryView(topics, { query, sort })

  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading')
    loadTopicDirectory(dataset, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setTopics(result); setStatus('ready') } })
      .catch(() => { if (!controller.signal.aborted) setStatus('error') })
    return () => controller.abort()
  }, [dataset, attempt])

  useEffect(() => {
    if (status !== 'ready') return
    const topicId = new URLSearchParams(window.location.search).get('topic')
    if (topicId) document.getElementById('directory-' + topicId)?.scrollIntoView({ block: 'start' })
  }, [status])

  function update(values) {
    const url = new URL(window.location.href)
    for (const [key, value] of Object.entries(values)) {
      if (!value || (key === 'dataset' && value === 'public')) url.searchParams.delete(key)
      else url.searchParams.set(key, value)
    }
    window.history.replaceState(window.history.state, '', url.pathname + url.search)
  }

  function chooseDataset(next) {
    setDataset(next); setQuery(''); setClosed(new Set())
    update({ dataset: next, q: null, topic: null })
  }

  function discussionLink(discussion) {
    const target = new URL(discussionURL(discussion.id, dataset), window.location.origin)
    const index = new URL(window.location.href)
    index.searchParams.set('topic', discussion.topicId)
    target.searchParams.set('indexReturn', index.pathname + index.search)
    return target.pathname + target.search
  }

  return <CivicPage variant="explore"><main className="exploration-container exploration-main topic-index" id="main-content" data-testid="topic-index">
    <nav className="page-breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a><span aria-hidden="true">›</span><span aria-current="page">Topics</span></nav>
    <header className="topic-heading"><h1>Explore topics</h1></header>
    <div className="civic-dataset-switch" role="group" aria-label="Discussion dataset"><button aria-pressed={dataset === 'public'} onClick={() => chooseDataset('public')}>Public discussions</button><button aria-pressed={dataset === 'demo'} onClick={() => chooseDataset('demo')}>Example data</button></div>
    {dataset === 'demo' && <p className="directory-example-note">Illustrative discussions and contributions.</p>}
    <div className="directory-controls">
      <div><label htmlFor="directory-search">Search topics and discussions</label><input id="directory-search" type="search" value={query} onChange={event => { setQuery(event.target.value); update({ q: event.target.value }) }} placeholder="Find a discussion" /></div>
      <div><label htmlFor="discussion-sort">Sort discussions</label><select id="discussion-sort" value={sort} onChange={event => { setSort(event.target.value); update({ sort: event.target.value }) }}>{DISCUSSION_SORTS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select></div>
    </div>
    <div className="directory-results" aria-busy={status === 'loading'}>
      {status === 'loading' ? <p className="civic-topic-message" role="status">Loading topics…</p> : status === 'error' ? <div className="understanding-empty"><p role="alert">Topics could not be loaded.</p><button className="civic-text-button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>
        : !visible.length ? <div className="understanding-empty"><h2>{query ? 'No matching topics or discussions' : 'No public discussions yet'}</h2>{query ? <button className="civic-text-button" onClick={() => { setQuery(''); update({ q: null }) }}>Clear search</button> : <button className="civic-text-button" onClick={() => chooseDataset('demo')}>Explore an example →</button>}</div>
        : visible.map(topic => <details className="directory-topic" key={topic.id} id={'directory-' + topic.id} open={!closed.has(topic.id)}>
          <summary onClick={event => { event.preventDefault(); setClosed(current => { const next = new Set(current); if (next.has(topic.id)) next.delete(topic.id); else next.add(topic.id); return next }) }}><h2>{topic.title}</h2><span>{topic.discussions.length} discussion{topic.discussions.length === 1 ? '' : 's'}</span><span aria-hidden="true">{closed.has(topic.id) ? '+' : '−'}</span></summary>
          <ul className="directory-discussions">{topic.discussions.map(discussion => <li key={discussion.id}><a href={discussionLink(discussion)}><div><h3>{discussion.title}</h3><p>{discussion.contributionCount} contribution{discussion.contributionCount === 1 ? '' : 's'} <span aria-hidden="true">·</span> <span>{sort === 'newest' ? 'Started' : 'Last contribution'} {dateLabel(sort === 'newest' ? discussion.createdAt : discussion.lastContributionAt)}</span></p></div><span aria-hidden="true">→</span></a></li>)}</ul>
          {!topic.discussions.length && <p className="directory-no-discussions">No discussions available yet.</p>}
        </details>)}
    </div>
    <p className="civic-sr-only" role="status">{status === 'ready' ? `${visible.length} topics. Discussions sorted by ${discussionSort(sort).label.toLowerCase()}.` : ''}</p>
  </main></CivicPage>
}
