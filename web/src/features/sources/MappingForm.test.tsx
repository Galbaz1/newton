import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { Source } from '../../api/types'
import { MappingForm } from './MappingForm'

it('offers late columns for mapping while rendering only captured preview cells', () => {
  const columns = Array.from({ length: 100 }, (_, i) => `column${i}`)
  const source: Source = {
    id: 'synthetic', company_id: 'company', machine_id: 'machine', filename: 'wide.csv',
    media_type: 'text/csv', sha256: 'a'.repeat(64), kind: 'timeseries', status: 'needs_mapping',
    revision: '', version: 1, mapping: null, created_at: '2026-09-22T00:00:00Z',
    metadata: { columns, sample_rows: [Object.fromEntries(columns.slice(0, 20).map(c => [c, '7']))] },
  }
  const html = renderToStaticMarkup(<MappingForm source={source} onSaved={() => {}} />)
  expect(html.match(/<option value="column99"/g)).toHaveLength(2)
  expect(html.match(/<th scope="col"/g)).toHaveLength(20)
  expect(html.match(/<td>/g)).toHaveLength(20)
  expect(html).toContain('first 20 of 100 columns')
})
