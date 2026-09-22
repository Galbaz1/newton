import { describe, expect, it } from 'vitest'
import { formatUtc } from './format'

describe('formatUtc', () => {
  it('keeps the UTC clock and labels it, whatever the viewer zone', () => {
    expect(formatUtc('2026-03-12T09:00:00Z')).toBe('12 Mar 2026, 09:00:00 UTC')
  })

  it('converts offsets to the same instant in UTC', () => {
    expect(formatUtc('2026-03-12T11:00:00+02:00')).toBe('12 Mar 2026, 09:00:00 UTC')
  })

  it('echoes unparseable input and marks missing input', () => {
    expect(formatUtc('not a time')).toBe('not a time')
    expect(formatUtc(null)).toBe('—')
  })
})
