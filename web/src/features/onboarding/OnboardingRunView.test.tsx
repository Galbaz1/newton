import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { OnboardingRun } from '../../api/types'
import type { Resource } from '../../lib/useResource'
import { OnboardingRunView } from './OnboardingRunView'
import { StarterQuestions } from './StarterQuestions'

const sha = 'f'.repeat(64)
const run: OnboardingRun = {
  id: 'run', company_id: 'c', website: 'https://example.test', data_class: 'synthetic', status: 'running',
  stage: 'profiling', summary: 'Twee bronnen gelezen.', created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:02Z',
  profile: { overview: 'Metaalbewerker', claims: [{ text: 'Maakt persen', url: 'https://example.test/over', title: 'Over ons', retrieved_at: '2026-09-22T00:00:01Z' }] },
  items: [{
    id: 'i1', filename: 'log.csv', sha256: sha, kind: 'timeseries', status: 'quarantined', data_class: 'synthetic',
    machine_id: null, source_id: 's1', profile: { rows: 12 },
    findings: [{ code: 'TZ_UNRESOLVED', severity: 'error', message: 'Tijdzone van kolom "t" kon niet worden vastgesteld; de volledige melding blijft zichtbaar.' }],
  }],
  events: [{ at: '2026-09-22T00:00:01Z', kind: 'error', message: 'Volledige foutmelding van de server.', item_id: 'i1' }],
  questions: [
    { id: 'q1', text: 'Wat is de maximale persdruk?', origin: 'role', state: 'ready', machine_id: 'm1', source_ids: ['s1'], reason: 'Rol operator' },
    { id: 'q2', text: 'Wanneer was het laatste onderhoud?', origin: 'source', state: 'missing', machine_id: null, source_ids: [], reason: 'Geen onderhoudslog' },
  ],
  pending_questions: [{ id: 'p1', question: 'Welke tijdzone gebruikt log.csv?', reason: 'Naïeve tijdstempels', source_ids: ['s1'] }],
}

function resource(data: OnboardingRun): Resource<OnboardingRun> {
  return { data, error: null, loading: false, reload: async () => {}, setData: () => {} }
}

describe('OnboardingRunView', () => {
  const html = renderToStaticMarkup(
    <OnboardingRunView run={resource(run)} companyName="Demo BV" onOpenQuestion={async () => {}} onInspectSource={() => {}} />,
  )

  it('shows a persistent synthetic banner, pause for a running run and no upload form', () => {
    expect(html).toContain('role="alert"')
    expect(html).toContain('Synthetic data')
    expect(html).toContain('Pause</button>')
    expect(html).not.toContain('Resume</button>')
    expect(html).not.toContain('Add files')
  })

  it('shows full hashes, quarantine findings, complete failure messages and claim links', () => {
    expect(html).toContain(sha)
    expect(html).toContain('TZ_UNRESOLVED')
    expect(html).toContain('de volledige melding blijft zichtbaar')
    expect(html).toContain('Volledige foutmelding van de server.')
    expect(html).toContain('href="https://example.test/over"')
    expect(html).toContain('Welke tijdzone gebruikt log.csv?')
  })

  it('offers resume and file upload for a paused run', () => {
    const paused = renderToStaticMarkup(
      <OnboardingRunView run={resource({ ...run, status: 'paused', data_class: 'original' })} companyName={null} onOpenQuestion={async () => {}} onInspectSource={() => {}} />,
    )
    expect(paused).toContain('Resume</button>')
    expect(paused).not.toContain('Pause</button>')
    expect(paused).toContain('Add files')
    expect(paused).not.toContain('role="alert"')
  })
})

describe('StarterQuestions', () => {
  it('renders ready questions as enabled buttons and missing ones disabled with their reason', () => {
    const html = renderToStaticMarkup(<StarterQuestions questions={run.questions} onOpen={() => {}} />)
    expect(html.match(/<button[^>]*class="question-button"[^>]*>/g)).toHaveLength(2)
    expect(html).toMatch(/<button type="button" class="question-button" aria-describedby="question-reason-q1">/)
    expect(html).toMatch(/<button type="button" class="question-button" disabled="" aria-describedby="question-reason-q2">/)
    expect(html).toContain('Geen onderhoudslog')
    expect(html).toContain('no machine linked')
  })
})

describe('StarterQuestions capability and scope', () => {
  it('states the capability and the exact channel/period of a measurement_summary question', () => {
    const html = renderToStaticMarkup(
      <StarterQuestions
        questions={[{ ...run.questions[0]!, capability: 'measurement_summary', measurement: { source_id: 's1', channel: 'p', start: '2026-01-01T00:00:00', end: null } }]}
        onOpen={() => {}}
      />,
    )
    expect(html).toContain('measurement summary')
    expect(html).toContain('channel p · 2026-01-01T00:00:00 to end (inclusive)')
  })
})
