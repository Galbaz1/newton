import { describe, expect, it } from 'vitest'
import { formatUtc } from './format'
import { SOURCE_LOCAL_LABEL, formatObservation, periodValue, seriesTimeMs, timeBasisOf } from './timeBasis'

describe('timeBasisOf', () => {
  it('defaults older fixtures to absolute', () => {
    expect(timeBasisOf(undefined)).toBe('absolute')
    expect(timeBasisOf('source_local')).toBe('source_local')
  })
})

describe('seriesTimeMs (source_local)', () => {
  it('uses components only, so the browser zone cannot shift points', () => {
    const t = seriesTimeMs('2026-03-29T02:30:00', 'source_local')
    // Same components as a UTC instant, regardless of TZ env; 02:30 on a DST-gap day still exists.
    expect(t).toBe(Date.UTC(2026, 2, 29, 2, 30, 0, 0))
    // Original process TZ (whatever it is) does not matter: the local Date parser is never used.
    expect(t - seriesTimeMs('2026-03-29T01:30:00', 'source_local')).toBe(60 * 60 * 1000)
    expect(seriesTimeMs('2026-03-29 02:30:00.5', 'source_local')).toBe(Date.UTC(2026, 2, 29, 2, 30, 0, 500))
    expect(seriesTimeMs('2026-03-29', 'source_local')).toBe(Date.UTC(2026, 2, 29))
    expect(Number.isNaN(seriesTimeMs('yesterday', 'source_local'))).toBe(true)
  })
  it('keeps the offset-aware parser for absolute timestamps', () => {
    expect(seriesTimeMs('2026-01-01T00:00:00+02:00', 'absolute')).toBe(Date.UTC(2025, 11, 31, 22))
  })
})

describe('formatObservation', () => {
  it('shows source-local strings verbatim and never labels them UTC', () => {
    const shown = formatObservation('2026-01-02T03:04:00', 'source_local', formatUtc)
    expect(shown).toBe('2026-01-02T03:04:00')
    expect(shown).not.toContain('UTC')
    expect(SOURCE_LOCAL_LABEL).toBe('Bronkloktijd · tijdzone onbevestigd')
  })
  it('labels absolute observations UTC', () => {
    expect(formatObservation('2026-01-02T03:04:00Z', 'absolute', formatUtc)).toMatch(/UTC$/)
  })
})

describe('periodValue', () => {
  it('passes source-local bounds unchanged and converts absolute bounds to an explicit instant', () => {
    expect(periodValue('2026-01-02T03:04', 'source_local')).toBe('2026-01-02T03:04')
    expect(periodValue('', 'source_local')).toBe('')
    const absolute = periodValue('2026-01-02T03:04', 'absolute')
    expect(absolute).toMatch(/Z$/)
    expect(Date.parse(absolute)).toBe(new Date('2026-01-02T03:04').getTime())
  })
})
