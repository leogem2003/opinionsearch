import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import LandingPage, { CivicPage } from './components/LandingPage'
import { topicIndexURL } from './components/understanding/api'
import './index.css'

const LegalPage = lazy(() => import('./components/legal/LegalPage'))
const TopicIndexPage = lazy(() => import('./components/understanding/TopicIndexPage'))
const DiscussionPage = lazy(() => import('./components/understanding/DiscussionPage'))
const ContributionPage = lazy(() => import('./components/understanding/ContributionPage'))

let path = window.location.pathname.replace(/\/+$/, '') || '/'
const topicMatch = path.match(/^\/topics\/([a-z0-9-]+)$/)
const discussionMatch = path.match(/^\/discussions\/([a-z0-9-]+)$/)
const contributionMatch = path.match(/^\/contributions\/([A-Za-z0-9_-]{1,128})$/)

// Old broad-topic links now open their group in the topic index.
if (topicMatch) {
  const dataset = new URLSearchParams(window.location.search).get('dataset') === 'demo' ? 'demo' : 'public'
  window.history.replaceState(null, '', topicIndexURL(dataset, topicMatch[1]))
  path = '/topics'
}

// Session invitations no longer select a separate application on the home page.
if (path === '/') {
  const url = new URL(window.location.href)
  if (url.searchParams.has('code')) {
    url.searchParams.delete('code')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
  }
}

const LEGAL_ROUTES = {
  '/privacy-policy': 'privacy',
  '/terms-and-conditions': 'terms',
  // legacy short paths
  '/privacy': 'privacy',
  '/terms': 'terms',
}

const LEGAL_CANONICAL = {
  privacy: '/privacy-policy',
  terms: '/terms-and-conditions',
}

const legalDoc = LEGAL_ROUTES[path] || null

if (legalDoc && path !== LEGAL_CANONICAL[legalDoc] && window.history?.replaceState) {
  window.history.replaceState(null, '', LEGAL_CANONICAL[legalDoc])
}

function Root() {
  if (path === '/') return <LandingPage />
  if (path === '/topics') return <TopicIndexPage />
  if (discussionMatch) return <DiscussionPage discussionId={discussionMatch[1]} />
  if (contributionMatch) return <ContributionPage contributionId={contributionMatch[1]} />
  if (legalDoc) {
    return <LegalPage doc={legalDoc} />
  }
  return <CivicPage><main className="civic-feedback" id="main-content">
    <h1>Page not found</h1>
    <p>This link is unavailable.</p>
    <div className="civic-feedback-actions"><a className="civic-text-button" href="/">Back to home →</a><a className="civic-text-button" href="/topics">Explore topics →</a></div>
  </main></CivicPage>
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Suspense fallback={<p role="status" style={{ padding: '2rem' }}>Loading…</p>}>
      <Root />
    </Suspense>
  </React.StrictMode>
)
