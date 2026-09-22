import { describe, expect, it } from 'vitest'
import { parseSeriesExcerpt } from './seriesExcerpt'

const backendShape = {
  unit: '°C',
  time_column: 'timestamp',
  value_column: 'bearing_temp',
  summary: { count: 4, min: 61.2, max: 88.9, mean: 70.1, start: '2026-03-12T09:00:00+00:00', end: '2026-03-12T12:00:00+00:00' },
  first_observations: [{ time: '2026-03-12T09:00:00+00:00', value: 61.2 }],
  last_visible_observations: [{ time: '2026-03-12T12:00:00+00:00', value: 88.9 }],
  visible_series_truncated: false,
  calculation: 'Deterministic summary of all valid original CSV rows.',
}

describe('parseSeriesExcerpt', () => {
  it('reads the backend summary without changing values', () => {
    const parsed = parseSeriesExcerpt(JSON.stringify(backendShape))
    expect(parsed).toMatchObject({ unit: '°C', valueColumn: 'bearing_temp', count: 4, min: 61.2, max: 88.9 })
    expect(parsed?.first[0]).toEqual({ time: '2026-03-12T09:00:00+00:00', value: 61.2 })
  })

  it('returns null for plain text, other JSON and oversized input', () => {
    expect(parseSeriesExcerpt('Bearing temperature rose after 10:00.')).toBeNull()
    expect(parseSeriesExcerpt('{"note": "no summary"}')).toBeNull()
    expect(parseSeriesExcerpt('{broken')).toBeNull()
    expect(parseSeriesExcerpt(`{"summary":{},"pad":"${'x'.repeat(30_000)}"}`)).toBeNull()
  })

  it('drops malformed points instead of inventing values', () => {
    const parsed = parseSeriesExcerpt(
      JSON.stringify({ ...backendShape, first_observations: [{ time: 5, value: 'NaN' }, null] }),
    )
    expect(parsed?.first).toEqual([])
  })
})
