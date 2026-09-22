import type { SeriesPoint } from '../api/types'
import type { TimeBasis } from './timeBasis'

/**
 * Time-series evidence carries its excerpt as a JSON summary produced by the
 * backend. This module only *reads* it for display; the stored excerpt string
 * is never changed, and anything that is not that JSON shape returns null so
 * the caller shows the excerpt verbatim.
 */
export interface SeriesExcerpt {
  timeBasis: TimeBasis
  unit: string | null
  timeColumn: string | null
  valueColumn: string | null
  count: number | null
  min: number | null
  max: number | null
  mean: number | null
  start: string | null
  end: string | null
  first: SeriesPoint[]
  last: SeriesPoint[]
  truncated: boolean
  calculation: string | null
}

const MAX_EXCERPT_CHARS = 20_000
const MAX_POINTS = 10

type Json = Record<string, unknown>

const isObject = (value: unknown): value is Json =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const text = (value: unknown) => (typeof value === 'string' ? value.slice(0, 200) : null)
const finite = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null)

function points(value: unknown): SeriesPoint[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, MAX_POINTS).flatMap((item) => {
    if (!isObject(item)) return []
    const time = text(item.time)
    const v = finite(item.value)
    return time !== null && v !== null ? [{ time, value: v }] : []
  })
}

export function parseSeriesExcerpt(excerpt: string): SeriesExcerpt | null {
  if (excerpt.length > MAX_EXCERPT_CHARS || !excerpt.trimStart().startsWith('{')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(excerpt)
  } catch {
    return null
  }
  if (!isObject(parsed) || !isObject(parsed.summary)) return null
  const summary = parsed.summary
  return {
    timeBasis: parsed.time_basis === 'source_local' ? 'source_local' : 'absolute',
    unit: text(parsed.unit),
    timeColumn: text(parsed.time_column),
    valueColumn: text(parsed.value_column),
    count: finite(summary.count),
    min: finite(summary.min),
    max: finite(summary.max),
    mean: finite(summary.mean),
    start: text(summary.start),
    end: text(summary.end),
    first: points(parsed.first_observations),
    last: points(parsed.last_visible_observations),
    truncated: parsed.visible_series_truncated === true,
    calculation: text(parsed.calculation),
  }
}
