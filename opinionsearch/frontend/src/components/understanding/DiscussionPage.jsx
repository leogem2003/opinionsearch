import { useState } from 'react'
import { CivicPage } from '../LandingPage'
import { topicIndexURL } from './api'
import { exampleDiscussion, exampleOpinions } from './discussion-examples'
import OpinionAtlas from './OpinionAtlas'
import './understanding.css'
import './exploration.css'

export default function DiscussionPage({ discussionId }) {
  const discussion = exampleDiscussion(discussionId)
  const [reading, setReading] = useState(() => new URLSearchParams(window.location.search).get('tab') === 'contributions')
  const fallback = topicIndexURL(discussion?.dataset, discussion?.topicId)
  let indexURL = fallback
  try {
    const supplied = new URLSearchParams(window.location.search).get('indexReturn')
    const url = supplied && new URL(supplied, window.location.origin)
    if (url && url.origin === window.location.origin && url.pathname === '/topics' && url.searchParams.get('dataset') === discussion?.dataset) indexURL = url.pathname + url.search
  } catch { /* Use the canonical directory location. */ }

  function chooseReading(next) {
    setReading(next)
    const url = new URL(window.location.href)
    if (next) url.searchParams.set('tab', 'contributions')
    else url.searchParams.delete('tab')
    window.history.replaceState(window.history.state, '', url.pathname + url.search)
    requestAnimationFrame(() => document.getElementById(next ? 'discussion-reading-heading' : 'topic-positions')?.focus({ preventScroll: true }))
  }

  function sourceURL(item) {
    const url = new URL(window.location.href)
    url.searchParams.set('dataset', 'demo')
    const params = new URLSearchParams({ discussion: discussion.id, returnTo: url.pathname + url.search })
    return `/contributions/${item.id}?${params}`
  }

  return <CivicPage variant="explore"><main className="exploration-container exploration-main topic-page" id="main-content" data-testid="discussion-page">
    <nav className="page-breadcrumb" aria-label="Breadcrumb"><a href={indexURL}>Topics</a>{discussion && <><span aria-hidden="true">›</span><a href={indexURL}>{discussion.topic.title}</a></>}<span aria-hidden="true">›</span><span aria-current="page">Discussion</span></nav>
    {!discussion ? <div className="understanding-empty"><h1>Discussion unavailable</h1><a className="civic-text-button" href="/topics">Explore topics →</a></div> : <>
      <header className="topic-heading"><p className="topic-dataset">Example data · illustrative discussion</p><h1>{discussion.title}</h1></header>
      {reading ? <section className="topic-reading" aria-labelledby="discussion-reading-heading"><header className="topic-reading-heading"><div><button className="civic-text-button" onClick={() => chooseReading(false)}>← Back to positions and reasons</button><h2 id="discussion-reading-heading" tabIndex={-1}>Read the contributions</h2></div></header>
        {discussion.contributions.map(item => <article className="exploration-voice" key={item.id}><div className="exploration-voice-body"><h3>{item.text}</h3></div><a className="exploration-voice-link" href={sourceURL(item)}>Read contribution ↗</a></article>)}
      </section> : <OpinionAtlas discussionId={discussion.id} dataset="demo" loadOpinions={exampleOpinions} onReadAll={() => chooseReading(true)} />}
    </>}
  </main></CivicPage>
}
