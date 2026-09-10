import { useEffect, useId, useState } from 'react'
import { requestJSON } from './api'
import SearchSentiment from './SearchSentiment'
import './exploration.css'
import './opinion-search.css'

export default function OpinionSearch({ initialQuery = '' }) {
  const inputId = useId()
  const [query, setQuery] = useState(initialQuery)
  const [search, setSearch] = useState(() => initialQuery.trim() ? { query: initialQuery.trim() } : null)
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
    requestJSON(`/api/v1/opinions/?${new URLSearchParams({ query: search.query })}`, { signal: controller.signal })
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
  }, [search])

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
    <form role="search" aria-label="Search opinions" onSubmit={submit}>
      <label htmlFor={inputId}>Search opinions</label>
      <div className="opinion-search-controls">
        <input id={inputId} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="A topic or statement, such as affordable housing" required />
        <button className="civic-button" disabled={!query.trim() || status === 'loading'}>{status === 'loading' ? 'Searching…' : 'Search'}</button>
      </div>
    </form>
    <div aria-busy={status === 'loading'}>
      {status === 'idle' && <p className="opinion-search-note">Find related opinions by topic or statement.</p>}
      {status === 'loading' && <p className="opinion-search-note" role="status">Searching opinions…</p>}
      {status === 'error' && <div className="opinion-search-note"><p role="alert">{error}</p><button className="civic-text-button" onClick={() => setSearch({ ...search })}>Try again →</button></div>}
      {status === 'ready' && <>
        {data.results.length ? <SearchSentiment key={search.query} results={data.results} query={search.query} limit={data.limit} /> : <div className="search-no-results" role="status"><h2>No matching opinions yet</h2><p>Try another topic or a more specific phrase.</p></div>}
      </>}
    </div>
  </div>
}
