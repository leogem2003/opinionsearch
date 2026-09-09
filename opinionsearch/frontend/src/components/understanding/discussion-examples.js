// Hand-authored UI examples, separate from submitted contributions and tab-local demos.
// A later provider can replace this data without changing the directory's sorting contract.
const timestamp = day => Date.UTC(2026, 8, day, 12) / 1000

export const EXAMPLE_TOPICS = [
  { id: 'immigration', title: 'Immigration', description: 'Immigration and its effects on society.' },
  { id: 'energy', title: 'Energy', description: 'Energy supply, costs and everyday use.' },
  { id: 'education', title: 'Education', description: 'Schools, learning and access to education.' },
]

const definitions = [
  { id: 'example-housing', topicId: 'immigration', title: 'Immigration and housing availability', createdAt: timestamp(2), stanceSubject: 'Immigration is increasing pressure on housing', contributions: [
    { stance: 'supports', day: 8, position: 'I think immigration is increasing pressure on housing', reason: 'available homes have not kept up with demand', text: 'I think immigration is increasing pressure on housing because available homes have not kept up with demand.' },
    { stance: 'opposes', day: 6, position: 'I do not think immigration is increasing pressure on housing', reason: 'newcomers in my area mostly occupy previously empty homes', text: 'I do not think immigration is increasing pressure on housing because newcomers in my area mostly occupy previously empty homes.' },
    { stance: 'mixed', day: 7, position: 'Immigration can increase housing pressure where construction has not kept up.', condition: 'where construction has not kept up', text: 'Immigration can increase housing pressure where construction has not kept up.' },
  ] },
  { id: 'example-care-workers', topicId: 'immigration', title: 'Foreign workers in healthcare', createdAt: timestamp(5), stanceSubject: 'Recruiting healthcare workers from abroad', contributions: [
    { stance: 'supports', day: 9, position: 'I support recruiting healthcare workers from abroad', reason: 'our care home cannot fill its vacancies locally', text: 'I support recruiting healthcare workers from abroad because our care home cannot fill its vacancies locally.' },
    { stance: 'mixed', day: 8, position: 'I support international recruitment if we also invest in local training.', condition: 'if we also invest in local training', text: 'I support international recruitment if we also invest in local training.' },
  ] },
  { id: 'example-local-wages', topicId: 'immigration', title: 'Immigration and local wages', createdAt: timestamp(7), stanceSubject: 'Immigration improves local wages', contributions: [
    { stance: 'unclear', day: 7, text: 'How does immigration affect wages in different industries?' },
  ] },
  { id: 'example-nuclear-security', topicId: 'energy', title: 'Nuclear power and energy security', createdAt: timestamp(3), stanceSubject: 'Using nuclear power for energy security', contributions: [
    { stance: 'supports', day: 7, position: 'I support using nuclear power for energy security', reason: 'it can provide electricity throughout the year', text: 'I support using nuclear power for energy security because it can provide electricity throughout the year.' },
    { stance: 'opposes', day: 8, position: 'I oppose relying on nuclear power for energy security', reason: 'building new reactors would take too long to address current shortages', text: 'I oppose relying on nuclear power for energy security because building new reactors would take too long to address current shortages.' },
  ] },
  { id: 'example-electricity-costs', topicId: 'energy', title: 'Rising household electricity costs', createdAt: timestamp(6), stanceSubject: 'Current household electricity prices are affordable', contributions: [
    { stance: 'opposes', day: 6, position: 'Current electricity prices are not affordable for my household', reason: 'our bill has risen faster than our income', text: 'Current electricity prices are not affordable for my household because our bill has risen faster than our income.' },
  ] },
  { id: 'example-teacher-shortages', topicId: 'education', title: 'Teacher shortages in rural areas', createdAt: timestamp(1), stanceSubject: 'Teacher shortages are affecting rural education', contributions: [
    { stance: 'supports', day: 8, position: 'Teacher shortages are affecting rural education', reason: 'our school has repeatedly combined classes', text: 'Teacher shortages are affecting rural education because our school has repeatedly combined classes.' },
    { stance: 'unclear', day: 5, text: 'Are teacher vacancies harder to fill in smaller communities?' },
  ] },
  { id: 'example-classroom-phones', topicId: 'education', title: 'Smartphones in classrooms', createdAt: timestamp(8), stanceSubject: 'Using smartphones during lessons', contributions: [
    { stance: 'mixed', day: 8, position: 'Phones can help during lessons if their use is guided by the teacher.', condition: 'if their use is guided by the teacher', text: 'Phones can help during lessons if their use is guided by the teacher.' },
  ] },
]

export const EXAMPLE_DISCUSSIONS = definitions.map(discussion => ({
  ...discussion, dataset: 'demo', topic: EXAMPLE_TOPICS.find(topic => topic.id === discussion.topicId),
  contributions: discussion.contributions.map((item, index) => ({ ...item, id: `${discussion.id}-${index + 1}`, createdAt: timestamp(item.day) })),
  contributionCount: discussion.contributions.length,
  lastContributionAt: Math.max(...discussion.contributions.map(item => timestamp(item.day))),
}))

export function exampleDiscussion(id) {
  return EXAMPLE_DISCUSSIONS.find(discussion => discussion.id === id)
}

export function exampleContribution(id) {
  const discussion = EXAMPLE_DISCUSSIONS.find(item => item.contributions.some(source => source.id === id))
  const source = discussion?.contributions.find(item => item.id === id)
  if (!source) return null
  return { id, text: source.text, createdAt: source.createdAt, publication: 'published', dataset: 'demo',
    discussion: { id: discussion.id, title: discussion.title, topicId: discussion.topicId } }
}

export async function exampleOpinions({ discussionId, stance, cursor }) {
  const discussion = exampleDiscussion(discussionId)
  if (!discussion) throw new Error('Discussion unavailable')
  const offset = Number(cursor || 0)
  if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('Invalid example page')
  const passage = text => [{ quote: text }]
  const all = discussion.contributions.map(item => ({ id: item.id, stance: item.stance,
    statements: item.position ? [{ id: 'position', text: item.position, evidence: passage(item.text) }] : [],
    context: [{ text: item.text, evidence: passage(item.text) }],
    reasons: item.reason ? [{ relationshipId: 'reason', text: item.reason, for: item.position, relationshipEvidence: passage(item.text) }] : [],
    conditions: item.condition ? [{ relationshipId: 'condition', text: item.condition, for: item.position, relationshipEvidence: passage(item.text) }] : [],
  }))
  const filtered = stance === 'all' ? all : all.filter(item => item.stance === stance)
  return { discussion: { id: discussion.id, title: discussion.title, stanceSubject: discussion.stanceSubject },
    totalContributions: all.length,
    groups: [ ['supports', 'In favour'], ['opposes', 'Not in favour'], ['mixed', 'Mixed / conditional'], ['unclear', 'No clear overall position'] ]
      .map(([id, label]) => ({ id, label, count: all.filter(item => item.stance === id).length })),
    contributions: filtered.slice(offset, offset + 12), nextCursor: offset + 12 < filtered.length ? String(offset + 12) : null }
}
