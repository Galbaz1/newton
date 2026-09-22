import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { Evidence } from '../../api/types'
import { EvidenceProvenance } from './EvidenceProvenance'
import { targetFromEvidence } from './inspectTarget'

const evidence: Evidence = {
  id: 'E1', source_id: 'synthetic', filename: 'synthetic.csv', excerpt: '{}', revision: 'A',
  source_version: 2, kind: 'timeseries', original_url: '/api/sources/synthetic/original',
}

it('preserves historical timezone, unit and original hash through inspector selection', () => {
  const historical: Evidence = { ...evidence, original_sha256: 'a'.repeat(64), derivation: {
    method: 'csv-all-rows-summary-v1', row_count: 5002, visible_row_count: 5000,
    mapping: { time_column: 't', value_column: 'v', unit: 'bar', timezone: 'UTC' },
  } }
  const target = targetFromEvidence(historical, 'E1')
  const html = renderToStaticMarkup(<EvidenceProvenance evidence={target.evidence!} />)
  expect(html).toContain('a'.repeat(64))
  expect(html).toContain('UTC')
  expect(html).toContain('bar')
  expect(html).toContain('all 5002 original data rows')
  expect(html).toContain('First 5000 original rows')
  expect(html).toContain('No unit conversion or interpolation')
})

it('marks absent historical metadata without inventing a current mapping or hash', () => {
  const html = renderToStaticMarkup(<EvidenceProvenance evidence={evidence} />)
  expect(html).toContain('Not recorded in this answer')
  expect(html).toContain('Derivation details were not recorded')
  expect(html).not.toContain('Columns at answer time')
})

it('shows the exact native PDF page map and input hash captured with the answer', () => {
  const html = renderToStaticMarkup(<EvidenceProvenance evidence={{ ...evidence, model_input: {
    format: 'application/pdf', original_pages: [17, 18, 19], sha256: 'b'.repeat(64),
    bytes: 2000, operation: 'pdfium-copy-pages-v1',
  } }} />)
  expect(html).toContain('Original pages 17, 18, 19; copied as PDF, not transcribed')
  expect(html).toContain('b'.repeat(64))
  expect(html).not.toContain('Derivation details were not recorded')
})

it('describes text offsets without presenting them as original PDF byte offsets', () => {
  const html = renderToStaticMarkup(<EvidenceProvenance evidence={{ ...evidence, kind: 'document', derivation: {
    method: 'page-text-chunk-v1', page_id: 'p1', offset: 1400, max_characters: 1500, trim_whitespace: true,
  } }} />)
  expect(html).toContain('Stored page text, starting at character 1400')
  expect(html).toContain('surrounding whitespace trimmed')
})
