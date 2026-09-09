import { APP_NAME } from '../../constants/app'
import { CivicPage } from '../LandingPage'
import privacyContent from './privacy-content.json'
import termsContent from './terms-content.json'
import './legal-page.css'

const DOCS = {
  privacy: privacyContent,
  terms: termsContent,
}

export default function LegalPage({ doc }) {
  const page = DOCS[doc] || DOCS.privacy

  return (
    <CivicPage>
      <main className="legal-main" id="main-content" data-testid={`legal-${doc}`}>
        <nav className="legal-document-nav" aria-label="Prototype information">
          <a href="/privacy-policy" aria-current={doc === 'privacy' ? 'page' : undefined}>Privacy</a>
          <a href="/terms-and-conditions" aria-current={doc === 'terms' ? 'page' : undefined}>Prototype information</a>
        </nav>
        <p className="civic-eyebrow">About HiveMind</p>
        <h1>{page.title}</h1>
        <p className="legal-intro">{page.intro}</p>

        {page.sections.map((section) => (
          <section key={section.id} className="legal-section" aria-labelledby={section.id}>
            <h2 id={section.id}>{section.heading}</h2>
            {section.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}
          </section>
        ))}
        <a className="civic-text-button legal-back" href="/" data-testid="legal-back">← Back to {APP_NAME}</a>
      </main>
    </CivicPage>
  )
}
