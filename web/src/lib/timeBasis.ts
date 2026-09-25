/**
 * Time basis of a series: `absolute` timestamps carry an offset and may be
 * shown in UTC; `source_local` strings have no offset and are shown exactly as
 * the source wrote them, never converted through the browser's zone.
 */
export type TimeBasis = 'absolute' | 'source_local'

export const SOURCE_LOCAL_LABEL = 'Bronkloktijd · tijdzone onbevestigd'

/** Treat an omitted basis as absolute. */
export function timeBasisOf(value: string | null | undefined): TimeBasis {
  return value === 'source_local' ? 'source_local' : 'absolute'
}

const NAIVE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3})\d*)?)?)?$/

/**
 * Milliseconds for positioning only. Source-local strings are parsed by
 * components with Date.UTC so the browser zone (and its DST) never shifts
 * or reorders points; absolute strings use the regular parser.
 */
export function seriesTimeMs(time: string, basis: TimeBasis): number {
  if (basis === 'absolute') return Date.parse(time)
  const m = NAIVE.exec(time.trim())
  if (!m) return NaN
  const [, y, mo, d, h = '0', mi = '0', s = '0', ms = '0'] = m
  return Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), Number(ms.padEnd(3, '0')))
}

/** Label for an observation time: UTC for absolute, verbatim for source-local. */
export function formatObservation(time: string | null | undefined, basis: TimeBasis, formatUtc: (iso: string | null | undefined) => string): string {
  if (!time) return '—'
  return basis === 'source_local' ? time : formatUtc(time)
}

/**
 * Period bound for the series query from a `datetime-local` input value.
 * Source-local: passed unchanged (the source has no offset to convert to).
 * Absolute: converted from the browser zone to an explicit UTC instant.
 */
export function periodValue(local: string, basis: TimeBasis): string {
  const trimmed = local.trim()
  if (!trimmed) return ''
  if (basis === 'source_local') return trimmed
  const parsed = new Date(trimmed)
  return Number.isNaN(parsed.getTime()) ? trimmed : parsed.toISOString()
}
