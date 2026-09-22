import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Source } from '../../api/types'
import { EMPTY_SCOPE, MeasurementScopeForm, describeScope, measurableSources, scopeBlockReason, scopeForInvestigation, scopeFromQuestion, toScope } from './MeasurementScope'

const base: Source = {
  id: 's1', company_id: 'c', machine_id: 'm', filename: 'press.csv', media_type: 'text/csv', sha256: 'a'.repeat(64),
  kind: 'timeseries', status: 'ready', revision: '', version: 1, mapping: null, created_at: '2026-09-22T00:00:00Z',
  metadata: { channels: [{ column: 'p', label: 'Druk', unit: 'bar' }], time_basis: 'source_local' },
}
const absolute: Source = { ...base, id: 's2', filename: 'abs.csv', metadata: { channels: [{ column: 't', label: '', unit: '°C' }] } }
const sources = [base, absolute, { ...base, id: 's3', status: 'needs_mapping' as const }, { ...base, id: 's4', kind: 'document' as const }]

describe('measurableSources', () => {
  it('offers only ready time series with established channels', () => {
    expect(measurableSources(sources).map((s) => s.id)).toEqual(['s1', 's2'])
    expect(measurableSources(null)).toEqual([])
  })
})

describe('toScope', () => {
  it('sends nothing without a source and channel, so the whole-file default applies', () => {
    expect(toScope(EMPTY_SCOPE, sources)).toBeUndefined()
    expect(toScope({ ...EMPTY_SCOPE, sourceId: 's1' }, sources)).toBeUndefined()
  })
  it('passes source-local bounds exactly as typed and omits blanks', () => {
    expect(toScope({ sourceId: 's1', channel: 'p', start: '2026-01-02T03:04', end: '' }, sources)).toEqual({
      source_id: 's1', channel: 'p', start: '2026-01-02T03:04',
    })
  })
  it('converts absolute bounds to explicit UTC instants', () => {
    const scope = toScope({ sourceId: 's2', channel: 't', start: '2026-01-02T03:04', end: '2026-01-03T00:00' }, sources)
    expect(scope?.start).toMatch(/Z$/)
    expect(Date.parse(scope!.end!)).toBe(new Date('2026-01-03T00:00').getTime())
  })
})

describe('describeScope / form', () => {
  it('explains the selected scope including the source-local caveat', () => {
    const text = describeScope({ source_id: 's1', channel: 'p', start: '2026-01-02T03:04' }, sources)
    expect(text).toContain('press.csv · Druk [bar]')
    expect(text).toContain('from 2026-01-02T03:04 to end')
    expect(text).toContain('Source-local time · timezone unknown')
    expect(describeScope(undefined, sources)).toContain('full-file summary')
  })
  it('renders nothing without measurable sources and the collapsed control otherwise', () => {
    expect(renderToStaticMarkup(<MeasurementScopeForm sources={[]} draft={EMPTY_SCOPE} onDraft={() => {}} disabled={false} />)).toBe('')
    const html = renderToStaticMarkup(<MeasurementScopeForm sources={sources} draft={EMPTY_SCOPE} onDraft={() => {}} disabled={false} />)
    expect(html).toContain('Measurement period for this question (optional)')
    expect(html).toContain('aria-expanded="false"')
  })
})

describe('starter question scope propagation', () => {
  const offsetScope = { source_id: 's2', channel: 't', start: '2026-01-02T03:04:00+02:00', end: '2026-01-02T05:00:00+02:00' }
  const localScope = { source_id: 's1', channel: 'p', start: '2026-01-02T03:04:00', end: null }

  it('turns a question measurement into an exact draft and ignores older questions without one', () => {
    expect(scopeFromQuestion({ measurement: offsetScope })).toEqual({
      sourceId: 's2', channel: 't', start: '2026-01-02T03:04:00+02:00', end: '2026-01-02T05:00:00+02:00', exact: true,
    })
    expect(scopeFromQuestion({ measurement: localScope })).toEqual({ sourceId: 's1', channel: 'p', start: '2026-01-02T03:04:00', end: '', exact: true })
    expect(scopeFromQuestion({})).toBeNull()
    expect(scopeFromQuestion({ measurement: { source_id: '', channel: 'p' } })).toBeNull()
  })

  it('sends exact bounds verbatim: the absolute offset and the source-local clock survive, whatever the browser zone', () => {
    const absolute = toScope(scopeFromQuestion({ measurement: offsetScope })!, sources)
    expect(absolute).toEqual({ source_id: 's2', channel: 't', start: '2026-01-02T03:04:00+02:00', end: '2026-01-02T05:00:00+02:00' })
    const local = toScope(scopeFromQuestion({ measurement: localScope })!, sources)
    expect(local).toEqual({ source_id: 's1', channel: 'p', start: '2026-01-02T03:04:00' })
    // Even before the source list is loaded the payload is identical (no re-conversion depends on it).
    expect(toScope(scopeFromQuestion({ measurement: offsetScope })!, null)).toEqual(absolute)
  })

  it('blocks sending only while a prefilled scope waits for the source list', () => {
    const draft = scopeFromQuestion({ measurement: localScope })!
    expect(scopeBlockReason(draft, null)).toMatch(/sources are loading/)
    expect(scopeBlockReason(draft, sources)).toBeNull()
    expect(scopeBlockReason(EMPTY_SCOPE, null)).toBeNull()
    expect(describeScope(toScope(draft, sources), sources)).toContain('press.csv · Druk [bar] from 2026-01-02T03:04:00 to end (Source-local time · timezone unknown)')
  })

  it('never carries a scope into another investigation or machine', () => {
    const prefill = { investigationId: 'inv-1', scope: scopeFromQuestion({ measurement: localScope }) }
    expect(scopeForInvestigation(prefill, 'inv-1')).toEqual(prefill.scope)
    expect(scopeForInvestigation(prefill, 'inv-2')).toBeUndefined()
    expect(scopeForInvestigation(prefill, null)).toBeUndefined()
    expect(scopeForInvestigation(null, 'inv-1')).toBeUndefined()
  })

  it('renders the exact scope open with a release control instead of the editable grid', () => {
    const draft = scopeFromQuestion({ measurement: localScope })!
    const html = renderToStaticMarkup(<MeasurementScopeForm sources={sources} draft={draft} onDraft={() => {}} disabled={false} />)
    expect(html).toContain('Clear measurement period')
    expect(html).toContain('Exact measurement period from the starter question')
    expect(html).not.toContain('measurement-scope-grid')
    expect(html).toContain('press.csv · Druk [bar]')
    const loading = renderToStaticMarkup(<MeasurementScopeForm sources={null} draft={draft} onDraft={() => {}} disabled={false} />)
    expect(loading).toContain('sources are loading')
  })
})
