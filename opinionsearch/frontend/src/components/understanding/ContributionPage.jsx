import { useEffect, useMemo, useState } from 'react'
import { CivicPage } from '../LandingPage'
import { dateLabel, discussionReturnURL, receiptToken, stanceLabels, topicIndexURL } from './api'
import { contributionDemo, getContribution } from './contributions'
import { exampleContribution } from './discussion-examples'
import './understanding.css'
import './exploration.css'

export default function ContributionPage({ contributionId }) {
  const isExample = contributionId.startsWith('example-')
  const example = useMemo(() => exampleContribution(contributionId), [contributionId])
  const [token] = useState(() => isExample ? null : receiptToken(contributionId))
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    async function load() {
      try {
        if (isExample && !example) throw Object.assign(new Error('Example unavailable'), { status: 404 })
        const result = example || await getContribution(contributionId, { token, signal: controller.signal })
        if (!controller.signal.aborted) setData(result)
      } catch (err) {
        if (!controller.signal.aborted) setError(err)
      }
    }
    load()
    return () => controller.abort()
  }, [contributionId, token, example, isExample, attempt])

  const discussion = data?.discussion
  const returnURL = discussion ? discussionReturnURL(discussion.id, 'demo') : null
  const returnParams = returnURL ? new URL(returnURL, window.location.origin).searchParams : null
  const stance = returnParams?.get('stance')
  const returnLabel = returnParams?.get('tab') === 'contributions' ? 'All contributions' : Object.hasOwn(stanceLabels, stance) ? stanceLabels[stance] : discussion?.title

  return <CivicPage variant="explore">
    <main className="exploration-main contribution-exploration" id="main-content" data-testid="contribution-page">
      {!data ? <div className="exploration-night exploration-unavailable" role="status">
        <h1>{error?.status === 404 ? 'Contribution unavailable' : error ? 'Unable to load contribution' : 'Loading contribution…'}</h1>
        {error?.status === 404 ? <p>{isExample ? 'This example could not be found.' : 'Open this contribution in the browser tab you used to send it.'}</p> : error && <button className="civic-button" onClick={() => setAttempt(value => value + 1)}>Try again</button>}
        <a className="atlas-inline-button" href={isExample ? topicIndexURL('demo') : '/#share-issue'}>{isExample ? '← Back to topics' : '← Back to home'}</a>
      </div> : <>
        <section className="exploration-night"><div className="exploration-container">
          <nav className="page-breadcrumb" aria-label="Breadcrumb">
            <a href={isExample ? topicIndexURL('demo') : '/'}>{isExample ? 'Topics' : 'Home'}</a>
            {discussion && <><span aria-hidden="true">›</span><a href={returnURL}>{discussion.title}</a></>}
            <span aria-hidden="true">›</span><span aria-current="page">{isExample ? 'Contribution' : 'Your contribution'}</span>
          </nav>
          <header className="exploration-intro contribution-intro"><div>
            <div className="understanding-meta"><span className={`understanding-badge ${isExample || contributionDemo ? 'is-demo' : ''}`}>{isExample ? 'Interface example' : contributionDemo ? 'Demo · saved in this tab only' : 'Saved privately'}</span><span>{dateLabel(data.createdAt)}</span></div>
            <h1>{isExample ? 'Original contribution' : contributionDemo ? 'Your demo contribution is saved' : 'Your contribution is saved'}</h1>
          </div></header>
        </div></section>
        <div className="exploration-container contribution-reading">
          <section className="understanding-source" aria-labelledby="source-heading">
            <h2 id="source-heading">Original words</h2>
            <blockquote>{data.text}</blockquote>
          </section>
          {!isExample && <><p className="understanding-note">{contributionDemo ? 'This text is stored in this tab for demonstration.' : 'Keep this tab to return to your saved text.'}</p><a className="civic-text-button" href="/#share-issue">Share another issue →</a></>}
          {returnURL && <a className="atlas-source-link contribution-return" href={returnURL}>← Back to {returnLabel}</a>}
        </div>
      </>}
    </main>
  </CivicPage>
}
