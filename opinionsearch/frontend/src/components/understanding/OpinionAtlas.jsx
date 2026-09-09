import { useEffect, useId, useRef, useState } from 'react'
import { stanceLabels } from './api'
import './exploration.css'

const COLOURS = { supports: '#8fdbb6', opposes: '#ffa596', mixed: '#d0bcf4', unclear: '#b9ccd5' }

function reasonRows(item) {
  const rows = [
    ...item.reasons.map(reason => ({ ...reason, key: reason.relationshipId, label: 'Reason' })),
    ...item.conditions.map(condition => ({ ...condition, key: condition.relationshipId, label: 'Condition' })),
  ]
  return rows.length ? rows : [{ key: 'account', label: item.stance === 'unclear' ? 'Original account' : 'No reason stated',
    text: item.statements[0]?.text || item.context[0]?.text || 'Read the original contribution.',
    evidence: (item.statements.length ? item.statements : item.context).flatMap(unit => unit.evidence) }]
}

export default function OpinionAtlas({ discussionId, dataset, onReadAll, loadOpinions }) {
  const initial = new URLSearchParams(window.location.search)
  const [stance, setStance] = useState(() => Object.hasOwn(stanceLabels, initial.get('stance')) ? initial.get('stance') : 'all')
  const [cursor, setCursor] = useState(() => initial.get('after') || '')
  const [selectedId, setSelectedId] = useState(() => initial.get('opinion') || initial.get('focus'))
  const [selectedReason, setSelectedReason] = useState(() => initial.get('reason'))
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const detailRef = useRef(null)
  const chartRef = useRef(null)
  const restoredSource = useRef(false)
  const descriptionId = useId()
  const requestKey = stance + ':' + cursor

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    loadOpinions({ discussionId, dataset, stance, cursor, signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData({ ...result, requestKey }) })
      .catch(err => { if (!controller.signal.aborted) setError(err.status === 404 ? 'This discussion has no published contributions yet.' : 'Opinions could not be loaded. Please try again.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [discussionId, dataset, stance, cursor, attempt, loadOpinions])

  const page = data?.requestKey === requestKey ? data : null
  const contributions = page?.contributions || []
  const total = data?.totalContributions || 0
  const groups = data?.groups || []
  const selectedCount = stance === 'all' ? total : groups.find(item => item.id === stance)?.count || 0
  const hasSelection = stance !== 'all' || selectedId || cursor

  useEffect(() => {
    if (loading || !page || restoredSource.current || !selectedId) return
    const summary = detailRef.current?.querySelector('details[open] > summary')
    if (summary) { restoredSource.current = true; summary.focus({ preventScroll: true }); summary.scrollIntoView({ block: 'center' }) }
  }, [loading, page, selectedId])

  function remember(values) {
    const url = new URL(window.location.href)
    for (const [key, value] of Object.entries(values)) {
      if (!value || value === 'all') url.searchParams.delete(key)
      else url.searchParams.set(key, value)
    }
    for (const key of ['group', 'statement', 'focus']) url.searchParams.delete(key)
    window.history.replaceState(window.history.state, '', url.pathname + url.search)
  }

  function chooseStance(next) {
    setStance(next); setCursor(''); setSelectedId(null); setSelectedReason(null)
    restoredSource.current = true
    remember({ stance: next, after: null, opinion: null, reason: null })
    if (next !== 'all') requestAnimationFrame(() => { detailRef.current?.focus({ preventScroll: true }); detailRef.current?.scrollIntoView({ block: 'start' }) })
  }

  function toggleReason(item, row, open) {
    restoredSource.current = true
    setSelectedId(open ? null : item.id); setSelectedReason(open ? null : row.key)
    remember({ opinion: open ? null : item.id, reason: open ? null : row.key })
  }

  function changePage(next) {
    setCursor(next || ''); setSelectedId(null); setSelectedReason(null)
    remember({ after: next, opinion: null, reason: null })
    detailRef.current?.focus()
  }

  function sourceURL(item, row) {
    const url = new URL(window.location.href)
    if (dataset === 'demo') url.searchParams.set('dataset', 'demo')
    url.searchParams.set('opinion', item.id)
    url.searchParams.set('reason', row.key)
    const params = new URLSearchParams({ discussion: discussionId, returnTo: url.pathname + url.search + '#opinion-' + item.id + '-' + row.key })
    return `/contributions/${encodeURIComponent(item.id)}?${params}`
  }

  function groupButton(item, secondary = false) {
    const percent = total ? Math.round(item.count / total * 100) : 0
    return <li key={item.id}><button className={'atlas-group' + (stance === item.id ? ' is-current' : '')} style={{ '--group-color': COLOURS[item.id] }} disabled={!item.count} aria-pressed={stance === item.id} onClick={() => chooseStance(item.id)}>
      <span className="atlas-group-top"><span className="atlas-group-name">{item.label}</span><span className="atlas-group-count">{item.count}<span className="civic-sr-only"> contributions</span><small> · {percent}%</small></span></span>
      {!secondary && <span className="atlas-bar-track" aria-hidden="true"><span style={{ width: (total ? item.count / total * 100 : 0) + '%' }} /></span>}
    </button></li>
  }

  return <section className="opinion-atlas" aria-label="Opinions in this discussion" data-testid="opinion-atlas">
    <section className="atlas-chart-panel" ref={chartRef} id="topic-positions" tabIndex={-1} aria-labelledby="positions-heading">
      <header className="atlas-chart-heading"><div><h2 id="positions-heading">Where people stand</h2><p id={descriptionId}>{data ? `On ${data.discussion.stanceSubject} · ${total} ${dataset === 'demo' ? 'example' : 'published'} contribution${total === 1 ? '' : 's'}` : loading ? 'Loading opinions…' : 'No published opinions yet'}</p></div>{stance !== 'all' && <button className="atlas-reset" onClick={() => chooseStance('all')}>Clear selection</button>}</header>
      {!data ? <div className="atlas-empty" role={error ? 'alert' : 'status'}>{error ? <><p>{error}</p><button onClick={() => setAttempt(value => value + 1)}>Try again</button></> : <><span className="atlas-loading-orbit" />Loading opinions…</>}</div>
        : <><ul className="atlas-groups" aria-label="In favour and not in favour" aria-describedby={descriptionId}>{groups.filter(item => ['supports', 'opposes'].includes(item.id)).map(item => groupButton(item))}</ul><ul className="atlas-groups atlas-other-positions" aria-label="Mixed and unclear positions" aria-describedby={descriptionId}>{groups.filter(item => ['mixed', 'unclear'].includes(item.id)).map(item => groupButton(item, true))}</ul></>}
      <p className="atlas-chart-note">{dataset === 'demo' ? 'Illustrative data. ' : ''}Counts are contributions, not a representative national poll.</p>
    </section>
    <section className="opinion-detail" ref={detailRef} tabIndex={-1} aria-labelledby="reasons-heading" aria-busy={loading}>
      <header className="opinion-detail-heading"><div><h2 id="reasons-heading">{stance === 'unclear' ? 'Original accounts' : stance === 'mixed' ? 'Reasons and conditions' : 'Reasons given'}</h2><p>{hasSelection ? `${stanceLabels[stance] || 'All positions'} · ${selectedCount} contribution${selectedCount === 1 ? '' : 's'}` : 'Select a position to explore its reasons.'}</p></div><button className="civic-text-button" onClick={onReadAll}>Read all contributions <span aria-hidden="true">→</span></button></header>
      {hasSelection && (loading ? <p className="opinion-message" role="status">Loading contributions…</p> : error ? <div className="opinion-message" role="alert"><p>{error}</p><button className="civic-text-button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>
        : contributions.length ? contributions.map(item => reasonRows(item).map((row, index) => {
          const open = selectedId === item.id && (selectedReason ? selectedReason === row.key : index === 0)
          return <details className="opinion-reason-row" key={item.id + ':' + row.key} id={'opinion-' + item.id + '-' + row.key} open={open}>
            <summary onClick={event => { event.preventDefault(); toggleReason(item, row, open) }}><span>{row.label !== 'Reason' && <span className="opinion-row-label">{row.label}</span>}{row.text}</span><span aria-hidden="true">{open ? '−' : '+'}</span></summary>
            <div className="opinion-reason-body">{row.for && <p className="opinion-connection">{row.label === 'Condition' ? 'Condition for' : 'Explains'}: {row.for}</p>}{(row.relationshipEvidence || row.evidence || []).map((passage, i) => <blockquote key={i}>{passage.quote}</blockquote>)}<a className="atlas-source-link" href={sourceURL(item, row)}>Read contribution <span aria-hidden="true">↗</span></a></div>
          </details>
        })) : <p className="opinion-message" role="status">No contributions in this view yet.</p>)}
      {hasSelection && (cursor || page?.nextCursor) && <nav className="opinion-pages" aria-label="Position pages"><span>{selectedCount} contributions · up to 12 per page</span>{cursor && <button className="civic-text-button" disabled={loading} onClick={() => changePage('')}>Back to newest</button>}{page?.nextCursor && <button className="civic-text-button" disabled={loading} onClick={() => changePage(page.nextCursor)}>Older contributions →</button>}</nav>}
      {hasSelection && <button className="civic-text-button opinion-back" onClick={() => { chartRef.current?.focus({ preventScroll: true }); chartRef.current?.scrollIntoView({ block: 'start' }) }}>↑ Back to positions</button>}
    </section>
    <footer className="atlas-method"><details><summary>How to read these positions</summary><div>
      <p>Each contribution counts once per discussion. All four positions share the same denominator. One person can write several contributions; these counts do not measure the whole population.</p>
      <p>Positions refer to the stated subject. Conditional or conflicting positions remain mixed / conditional. Questions, observations and earlier interpretations without an overall position remain unclear.</p>
      <p>Each reason or condition is attached to its own contribution and original words. Similar reasons have not been merged into groups, and inferred motives do not count as stated reasons.</p>
    </div></details></footer>
  </section>
}
