import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { APP_NAME } from '../constants/app'
import { issueTextError, saveReceipt, submissionKey, topicIndexURL } from './understanding/api'
import { loadTopicDirectory } from './understanding/topic-directory'
import { contributionDemo, createContribution } from './understanding/contributions'
import OpinionSearch from './understanding/OpinionSearch'
import PublicTopicDirectory from './understanding/PublicTopicDirectory'
import './landing-page.css'

function ArrowIcon() {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
}

function focusIssueInput() {
  requestAnimationFrame(() => document.getElementById('issue-message')?.focus({ preventScroll: true }))
}

function CivicMotif() {
  return (
    <svg className="civic-motif" viewBox="0 0 330 230" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="1">
        <path d="m165 24 64 37v74l-64 37-64-37V61l64-37Z" />
        <path d="m101 61-64 37v74l64 37 64-37M229 61l64 37v74l-64 37-64-37" />
        <path d="m165 98 64 37M165 98l-64 37M165 24v74M37 98l64 37M293 98l-64 37M165 98v74" />
        <circle cx="165" cy="98" r="22" fill="var(--civic-canvas)" />
        <circle cx="101" cy="61" r="5" fill="var(--civic-canvas)" />
        <circle cx="229" cy="135" r="5" fill="var(--civic-canvas)" />
        <circle cx="101" cy="209" r="4" fill="var(--civic-canvas)" />
      </g>
      <circle cx="165" cy="98" r="5" fill="#17394b" />
      <circle cx="165" cy="24" r="5" fill="#9d7b4b" />
      <circle cx="37" cy="172" r="4" fill="#9d7b4b" />
      <circle cx="293" cy="98" r="4" fill="#17394b" />
    </svg>
  )
}

export function CivicPage({ children, variant = 'default' }) {
  return (
    <div className={`civic-page ${variant === 'explore' ? 'exploration-shell' : ''}`}>
      <a className="civic-skip" href="#main-content">Skip to content</a>
      <header className="civic-header">
        <div className="civic-container civic-header-inner">
          <a className="civic-brand" href="/" aria-label={`${APP_NAME} home`}>
            <img className="civic-brand-mark" src="/brand/hivemind-symbol-128.png" width="56" height="56" alt="" />
            <span className="civic-brand-copy"><strong>{APP_NAME}</strong><span>Public dialogue</span></span>
          </a>
          <nav className="civic-nav" aria-label="Main navigation">
            <a href="/#share-issue" onClick={focusIssueInput}>Share an issue</a>
            <a href="/topics">Explore topics <ArrowIcon /></a>
          </nav>
        </div>
      </header>
      {children}
      <footer className="civic-footer">
        <div className="civic-container civic-footer-inner">
          <p><strong>{APP_NAME}</strong></p>
          <nav aria-label="Prototype information"><a href="/privacy-policy">Privacy</a><a href="/terms-and-conditions">Prototype information</a></nav>
        </div>
      </footer>
    </div>
  )
}

function IssueComposer() {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const pendingSubmission = useRef(null)

  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    const resize = () => {
      input.style.height = 'auto'
      input.style.height = `${Math.min(input.scrollHeight, 240)}px`
    }
    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [draft])

  useEffect(() => {
    if (window.location.hash === '#share-issue') focusIssueInput()
  }, [])

  async function sendIssue(event) {
    event.preventDefault()
    const text = draft.trim()
    if (sending) return
    const validation = issueTextError(draft)
    if (validation) { setError(validation); inputRef.current?.focus(); return }
    if (pendingSubmission.current?.text !== text) pendingSubmission.current = { text, key: submissionKey() }
    setSending(true)
    setError('')
    try {
      const result = await createContribution({ text, submissionKey: pendingSubmission.current.key })
      const saved = saveReceipt(result)
      // Keep the receipt out of the URL, including when session storage is unavailable.
      window.history.pushState(saved ? null : { opinionsearchReceipt: { id: result.id, accessToken: result.accessToken } }, '', `/contributions/${encodeURIComponent(result.id)}`)
      window.location.reload()
    } catch {
      setError('We couldn’t finish your submission. Your text is still here. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="civic-section civic-contribute" id="share-issue" aria-labelledby="issue-heading">
      <header className="civic-section-header">
        <div>
          <p className="civic-eyebrow civic-section-label"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4 4h16v12H10l-5 4v-4H4V4Z" /><path d="M8 8h8M8 12h5" /></svg>Contribute</p>
          <h2 id="issue-heading">Describe an issue</h2>
        </div>
      </header>
      <div className="civic-composer">
          <form onSubmit={sendIssue} aria-busy={sending}>
            <textarea
              id="issue-message"
              ref={inputRef}
              value={draft}
              onChange={(event) => { setDraft(event.target.value); setError('') }}
              placeholder="What’s happening, and what would you like to change?"
              rows={2}
              aria-labelledby="issue-heading"
              aria-invalid={error && issueTextError(draft) ? true : undefined}
              required
              readOnly={sending}
              aria-describedby={`issue-hint${error ? ' issue-error' : ''}`}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault()
                  event.currentTarget.form.requestSubmit()
                }
              }}
              data-testid="issue-input"
            />
            <div className="civic-composer-actions">
              <span className="civic-composer-hint" id="issue-hint">{contributionDemo ? 'Demo · saved in this tab only' : 'Your text will be publicly searchable'}</span>
              <button className="civic-button" type="submit" disabled={!draft.trim() || sending} data-testid="issue-send">
                {sending ? 'Sending…' : 'Send issue'} <ArrowIcon />
              </button>
            </div>
          </form>
      </div>
      {error && <p className="civic-error" id="issue-error" role="alert">{error}</p>}
    </section>
  )
}

function TopicBrowser() {
  const [topics, setTopics] = useState([])
  const [query, setQuery] = useState(() => new URLSearchParams(window.location.search).get('q') || '')
  const [status, setStatus] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const [dataset, setDataset] = useState(() => new URLSearchParams(window.location.search).get('topics') === 'demo' ? 'demo' : 'public')

  function updateBrowse(nextDataset, nextQuery) {
    setDataset(nextDataset); setQuery(nextQuery)
    const url = new URL(window.location.href)
    if (nextDataset === 'demo') url.searchParams.set('topics', 'demo')
    else url.searchParams.delete('topics')
    if (nextQuery) url.searchParams.set('q', nextQuery)
    else url.searchParams.delete('q')
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
  }

  useEffect(() => {
    if (dataset !== 'demo') return
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    let active = true
    setStatus('loading')
    loadTopicDirectory(dataset, { signal: controller.signal })
      .then((data) => {
        if (active) { setTopics(data); setStatus('ready') }
      })
      .catch(() => { if (active) setStatus('error') })
      .finally(() => clearTimeout(timeout))
    return () => { active = false; controller.abort(); clearTimeout(timeout) }
  }, [attempt, dataset])

  const matches = topics.filter((topic) =>
    `${topic.title} ${topic.description || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  )

  return (
    <section className="civic-section civic-topics" id="current-topics" aria-labelledby="topics-heading">
      <header className="civic-section-header">
        <div>
          <p className="civic-eyebrow civic-section-label"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="6" cy="7" r="3" /><circle cx="18" cy="7" r="3" /><circle cx="12" cy="18" r="3" /><path d="M9 7h6M7.5 10l3 5M16.5 10l-3 5" /></svg>Explore</p>
          <h2 id="topics-heading">{dataset === 'demo' ? 'Current topics' : 'Explore opinions'}</h2>
        </div>
        {dataset === 'demo' && <div className="civic-search">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
          <label className="civic-sr-only" htmlFor="topic-search">Search current topics</label>
          <input id="topic-search" type="search" placeholder="Search topics" value={query} onChange={(event) => updateBrowse(dataset, event.target.value)} disabled={status !== 'ready' || topics.length === 0} />
        </div>}
      </header>
      <div className="civic-dataset-switch" role="group" aria-label="Topic dataset"><button type="button" aria-pressed={dataset === 'public'} onClick={() => updateBrowse('public', '')}>Opinions</button><button type="button" aria-pressed={dataset === 'demo'} onClick={() => updateBrowse('demo', '')}>Example data</button></div>
      {dataset === 'public' ? <OpinionSearch initialQuery={query}><PublicTopicDirectory compact /></OpinionSearch> : <>
      <p className="civic-dataset-note">Illustrative discussions and contributions.</p>
      <p className="civic-sr-only" role="status">{status === 'ready' ? `${matches.length} topics found` : status === 'error' ? 'Topics could not be loaded' : 'Loading topics'}</p>
      <div className="civic-topic-content" aria-busy={status === 'loading'}>
        {status === 'loading' ? (
          <p className="civic-topic-message">Loading topics…</p>
        ) : status === 'error' ? (
          <div className="civic-topic-empty">
            <h3>Topics couldn’t be loaded</h3>
            <button className="civic-text-button" onClick={() => setAttempt((value) => value + 1)}>Try again <ArrowIcon /></button>
          </div>
        ) : topics.length === 0 ? (
          <div className="civic-topic-empty civic-topic-empty-with-icon" data-testid="topics-empty">
            <div className="civic-empty-emblem" aria-hidden="true">
              <svg viewBox="0 0 64 64" width="56" height="56" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M10 13h33v25H26l-10 8v-8h-6V13Z" fill="#fff" /><path d="M43 24h11v25h-7l-8 6v-6H28v-7" /><path d="M18 22h17M18 29h11" />
              </svg>
            </div>
            <div className="civic-empty-copy">
              <h3>No examples available yet</h3>
            </div>
          </div>
        ) : matches.length === 0 ? (
          <div className="civic-topic-empty"><h3>No matching topics</h3><button className="civic-text-button" onClick={() => updateBrowse(dataset, '')}>Clear search</button></div>
        ) : (
          <ul className="civic-topic-list">
            {matches.map((topic) => (
              <li key={topic.id}>
                <a href={topicIndexURL(dataset, topic.id)}>
                  <div><h3>{topic.title}</h3>{topic.description && <p>{topic.description}</p>}<span>{topic.discussions.length} discussion{topic.discussions.length === 1 ? '' : 's'} · Explore topic</span></div>
                  <ArrowIcon />
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
      </>}
      <a className="civic-text-button" href={topicIndexURL(dataset)}>{dataset === 'demo' ? 'Browse all topics' : 'Explore opinions'} <ArrowIcon /></a>
    </section>
  )
}

export default function LandingPage() {
  return (
    <CivicPage>
      <main className="civic-container civic-main" id="main-content" data-testid="landing">
        <div className="civic-intro">
          <div className="civic-intro-copy">
            <h1>What matters to<br className="civic-heading-break" /> your community?</h1>
            <p>Share an issue. Explore public topics.</p>
          </div>
          <CivicMotif />
        </div>
        <div className="civic-workspace"><IssueComposer /><TopicBrowser /></div>
      </main>
    </CivicPage>
  )
}
