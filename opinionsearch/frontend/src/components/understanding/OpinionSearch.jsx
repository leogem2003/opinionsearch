import { useEffect, useId, useState } from 'react'
import { requestJSON } from './api'
import SearchSentiment from './SearchSentiment'
import './exploration.css'
import './opinion-search.css'

export default function OpinionSearch({ initialQuery = '', topic = null, children }) {
  const inputId = useId()
  const [query, setQuery] = useState(initialQuery)
  const [search, setSearch] = useState(() => initialQuery.trim() || topic ? { query: initialQuery.trim() } : null)
  const [data, setData] = useState({ results: [], limit: 50 })
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!search) return
    if ([...search.query].length > 2000 || search.query.includes('\0')) {
      setError('Use a search of at most 2,000 characters.')
      setStatus('error')
      return
    }
    const controller = new AbortController()
    setStatus('loading')
    requestJSON(`/api/v1/opinions/?${new URLSearchParams({ query: search.query, ...(topic ? { topic: topic.id } : {}) })}`, { signal: controller.signal })
      .then(result => {
        if (!Array.isArray(result.results) || !Number.isInteger(result.limit) || result.results.some(item =>
          typeof item.id !== 'string' || typeof item.text !== 'string' || typeof item.topic !== 'string')) {
          throw new Error('Invalid search response')
        }
        if (!controller.signal.aborted) { setData(result); setStatus('ready') }
      })
      .catch(() => {
        if (!controller.signal.aborted) { setError('Search is unavailable right now. Please try again.'); setStatus('error') }
      })
    return () => controller.abort()
  }, [search, topic?.id])

  function browseTopics() {
    setQuery(''); setSearch(null); setStatus('idle')
    const url = new URL(window.location.href)
    url.searchParams.delete('q')
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
  }

  function submit(event) {
    event.preventDefault()
    const text = query.trim()
    if (!text) return
    const url = new URL(window.location.href)
    url.searchParams.set('q', text)
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
    setSearch({ query: text })
  }

  return <div className="opinion-search" data-testid="opinion-search">
    {!topic && <form role="search" aria-label="Search opinions" onSubmit={submit}>
      <label htmlFor={inputId}>Search opinions</label>
      <div className="opinion-search-controls">
        <input id={inputId} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="A topic or statement, such as affordable housing" required />
        <button className="civic-button" disabled={!query.trim() || status === 'loading'}>{status === 'loading' ? 'Searching…' : 'Search'}</button>
      </div>
      {search && children && <button type="button" className="civic-text-button search-browse-return" onClick={browseTopics}>← Browse topics</button>}
    </form>}
    <div aria-busy={status === 'loading'}>
      {status === 'idle' && (children || <p className="opinion-search-note">Find related opinions by topic or statement.</p>)}
      {status === 'loading' && <p className="opinion-search-note" role="status">Searching opinions…</p>}
      {status === 'error' && <div className="opinion-search-note"><p role="alert">{error}</p><button className="civic-text-button" onClick={() => setSearch({ ...search })}>Try again →</button></div>}
      {status === 'ready' && <>
        {data.results.length ? <SearchSentiment key={search.query} results={data.results} query={search.query || topic?.title} limit={data.limit} topic={topic} /> : <div className="search-no-results" role="status"><h2>{topic ? 'No opinions in this topic yet' : 'No matching opinions yet'}</h2>{topic ? <a className="civic-text-button" href="/#share-issue">Share an issue →</a> : <p>Try another topic or a more specific phrase.</p>}</div>}
      </>}
    </div>
  </div>
}
