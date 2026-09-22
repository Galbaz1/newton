import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { Source } from '../../api/types'
import { InspectorPanel } from './InspectorPanel'
import { targetFromSource } from './inspectTarget'

it('retains the original download while withholding quarantined charts and period controls', () => {
  const source: Source = {
    id: 'quarantined-series', company_id: 'company', machine_id: 'machine',
    filename: 'synthetic-backward-times.csv', media_type: 'text/csv',
    sha256: 'a'.repeat(64), kind: 'timeseries', status: 'quarantined',
    revision: '', version: 1, mapping: null, metadata: {}, created_at: '',
  }
  const html = renderToStaticMarkup(
    <InspectorPanel target={targetFromSource(source)} sources={[source]} onClose={() => {}} />,
  )
  expect(html).toContain('This source is quarantined');
  expect(html).toContain('Download original');
  expect(html).not.toContain('datetime-local');
  expect(html).not.toContain('Loading original series');
  expect(html).not.toContain('UTC instant');
  expect(html).not.toContain('has since been deleted');
})
