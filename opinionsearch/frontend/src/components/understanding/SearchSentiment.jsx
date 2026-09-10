import { useId, useState } from 'react'

const GROUPS = [
  { id: 'positive', label: 'Positive', colour: '#8fdbb6' },
  { id: 'negative', label: 'Negative', colour: '#ffa596' },
  { id: 'neutral', label: 'Neutral', colour: '#d0bcf4' },
  { id: 'unscored', label: 'Not yet analysed', colour: '#b9ccd5' },
]

export function sentimentGroup(score) {
  if (!Number.isInteger(score) || score < 1 || score > 5) return 'unscored'
  return score < 3 ? 'negative' : score > 3 ? 'positive' : 'neutral'
}

function DotCluster({ count }) {
  return <svg className="search-cluster" viewBox="0 0 240 166" aria-hidden="true">
    <ellipse cx="120" cy="83" rx="108" ry="73" className="search-cluster-boundary" />
    {Array.from({ length: count }, (_, index) => {
      const angle = index * 2.39996323
      const radius = count === 1 ? 0 : Math.sqrt(index + .5) * 8.6
      return <circle key={index} cx={120 + Math.cos(angle) * radius * 1.4} cy={83 + Math.sin(angle) * radius} r="4.5" />
    })}
  </svg>
}

export default function SearchSentiment({ results, query, limit }) {
  const headingId = useId()
  const readingId = useId()
  const [selected, setSelected] = useState('all')
  const groups = GROUPS.map(group => ({ ...group, items: results.filter(item => sentimentGroup(item.sentiment) === group.id) }))
  const visible = selected === 'all' ? results : groups.find(group => group.id === selected).items

  function choose(id) { setSelected(current => current === id ? 'all' : id) }

  return <section className="search-positions" aria-label={`Sentiment in results for ${query}`}>
    <section className="atlas-chart-panel" aria-labelledby={headingId}>
      <header className="atlas-chart-heading"><div>
        <p className="search-map-eyebrow">Opinion overview</p>
        <h2 id={headingId}>Sentiment around “{query}”</h2>
        <p>{results.length}{results.length === limit ? ` closest matches · limit ${limit}` : ` matching opinion${results.length === 1 ? '' : 's'}`}</p>
      </div>{selected !== 'all' && <button className="atlas-reset" onClick={() => setSelected('all')}>All views</button>}</header>
      <div className="search-cluster-pair" role="group" aria-label="Filter by sentiment">
        {groups.slice(0, 2).map(group => <button key={group.id} className={`search-cluster-group${selected === group.id ? ' is-current' : ''}`} style={{ '--position-colour': group.colour }} aria-pressed={selected === group.id} disabled={!group.items.length} onClick={() => choose(group.id)}>
          <span className="search-cluster-heading"><span>{group.label}</span><strong>{group.items.length}</strong></span>
          <DotCluster count={group.items.length} />
          <span className="search-cluster-caption">{group.items.length ? 'Explore these opinions →' : 'No matches in this group'}</span>
        </button>)}
      </div>
      <div className="search-other-positions" role="group" aria-label="Neutral and unanalysed opinions">
        {groups.slice(2).map(group => <button key={group.id} style={{ '--position-colour': group.colour }} aria-pressed={selected === group.id} disabled={!group.items.length} onClick={() => choose(group.id)}><span>{group.label}</span><strong>{group.items.length}</strong></button>)}
      </div>
      <p className="atlas-chart-note">One dot per matching opinion. Sentiment describes tone, not agreement with the topic.</p>
    </section>

    <section className="opinion-detail" aria-labelledby={readingId}>
      <header className="opinion-detail-heading"><div><h2 id={readingId}>Original words</h2><p role="status">{selected === 'all' ? 'All views' : GROUPS.find(group => group.id === selected).label} · {visible.length} opinion{visible.length === 1 ? '' : 's'}</p></div>{selected !== 'all' && <button className="civic-text-button" onClick={() => setSelected('all')}>Show all opinions →</button>}</header>
      {visible.map(item => <details className="opinion-reason-row search-opinion-row" key={item.id}>
        <summary><span><span className="opinion-row-label">{GROUPS.find(group => group.id === sentimentGroup(item.sentiment)).label}{item.topic ? ` · ${item.topic}` : ''}</span>{item.text}</span><span className="search-row-expand" aria-hidden="true">+</span></summary>
        <div className="opinion-reason-body">
          <p className="opinion-connection">{sentimentGroup(item.sentiment) === 'unscored' ? 'This opinion does not have a sentiment score yet.' : `Model sentiment score: ${item.sentiment}/5. This estimates the tone of the original text; it does not measure support for “${query}”.`}</p>
          <p className="search-source-reference">Opinion {item.id}{item.contributionId ? ` · Source ${item.contributionId}` : ''}</p>
        </div>
      </details>)}
      {!visible.length && <p className="opinion-message">No opinions in this group.</p>}
    </section>

    <footer className="atlas-method"><details><summary>How to read this view</summary><div>
      <p>This view covers only the returned search results, up to {limit}. Counts are opinions, not unique people or a national poll.</p>
      <p>The backend sentiment model assigns a score from 1 to 5: 1–2 are grouped as negative, 3 as neutral, and 4–5 as positive. Missing scores remain unanalysed. These are model estimates, not labels supplied by contributors.</p>
      <p>A positive or negative tone does not establish whether someone is in favour of the searched topic. Topic-specific stance and supporting reasons require a separate analysis step.</p>
      <p>Dots show group membership. Their positions within each group are for layout and do not measure similarity, strength of opinion or distance between people.</p>
    </div></details></footer>
  </section>
}
