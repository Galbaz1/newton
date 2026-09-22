import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { SeriesControls, toIsoOrBlank } from './SeriesControls'

it('offers only established channels plus the mapped default', () => {
  const html = renderToStaticMarkup(
    <SeriesControls
      channels={[{ column: 'temp_c', label: 'Temperatuur', unit: '°C' }, { column: 'p', label: '', unit: 'bar' }]}
      value={{}}
      onChange={() => {}}
    />,
  )
  expect(html).toContain('<option value="" selected="">Mapped default</option>')
  expect(html).toContain('<option value="temp_c">Temperatuur [°C]</option>')
  expect(html).toContain('<option value="p">p [bar]</option>')
  expect(html).toContain('type="datetime-local"')
  expect(html).not.toContain('Reset')
})

it('hides the channel selector without established channels and shows reset when filtered', () => {
  const html = renderToStaticMarkup(<SeriesControls channels={[]} value={{ start: '2026-01-01T00:00:00Z' }} onChange={() => {}} />)
  expect(html).not.toContain('<select')
  expect(html).toContain('Reset')
})

it('states the source-local basis and never converts for source_local', () => {
  const html = renderToStaticMarkup(<SeriesControls channels={[]} value={{}} onChange={() => {}} basis="source_local" />)
  expect(html).toContain('Bronkloktijd · tijdzone onbevestigd')
  expect(html).not.toContain('UTC instant')
})

it('keeps blank periods blank and converts local input to ISO', () => {
  expect(toIsoOrBlank('')).toBe('')
  expect(toIsoOrBlank('2026-01-02T03:04')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
  expect(toIsoOrBlank('not a date')).toBe('not a date')
})
