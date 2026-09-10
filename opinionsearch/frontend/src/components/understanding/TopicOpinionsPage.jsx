import { useEffect, useState } from 'react'
import { CivicPage } from '../LandingPage'
import { loadTopicDirectory } from './topic-directory'
import OpinionSearch from './OpinionSearch'
import './exploration.css'

export default function TopicOpinionsPage({ topicId }) {
  const [state, setState] = useState({ loading: true })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState({ loading: true })
    loadTopicDirectory('public', { signal: controller.signal })
      .then(topics => { if (!controller.signal.aborted) setState({ topic: topics.find(topic => topic.id === topicId) }) })
      .catch(() => { if (!controller.signal.aborted) setState({ error: true }) })
    return () => controller.abort()
  }, [topicId, attempt])
  return <CivicPage variant="explore"><main className="exploration-container exploration-main topic-page" id="main-content">
    <nav className="page-breadcrumb" aria-label="Breadcrumb"><a href="/topics">Topics</a><span aria-hidden="true">›</span><span aria-current="page">{state.topic?.title || 'Topic'}</span></nav>
    {state.loading ? <p role="status">Loading topic…</p> : state.error ? <div className="understanding-empty"><p role="alert">The topic could not be loaded.</p><button className="civic-text-button" onClick={() => setAttempt(value => value + 1)}>Try again →</button></div> : !state.topic ? <div className="understanding-empty"><h1>Topic unavailable</h1><a className="civic-text-button" href="/topics">Browse topics →</a></div> : <>
      <header className="topic-heading"><p className="topic-dataset">Public opinions</p><h1>{state.topic.title}</h1><p>{state.topic.description}</p></header>
      <OpinionSearch topic={state.topic} />
    </>}
  </main></CivicPage>
}
