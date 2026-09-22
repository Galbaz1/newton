import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { Series } from '../../api/types'
import { SeriesChart } from './SeriesChart'

const series: Series = {
  source_id: 'synthetic', unit: 'bar', time_column: 'time', value_column: 'pressure',
  points: [
    { time: '2026-09-22T09:00:00Z', value: 7 },
    { time: '2026-09-22T10:00:00Z', value: 9 },
  ],
  summary: {
    count: 3, min: 7, max: 11, mean: 9,
    start: '2026-09-22T09:00:00Z', end: '2026-09-22T11:00:00Z',
  },
  truncated: true,
}

it('provides a native keyboard selector with exact original time and value', () => {
  const html = renderToStaticMarkup(<SeriesChart series={series} filename="synthetic.csv" />)
  expect(html).toContain('type="range"')
  expect(html).toContain('aria-label="Inspect original point"')
  expect(html).toContain('min="0" max="1" step="1"')
  expect(html).toContain('aria-valuetext="Point 1 of 2: 2026-09-22T09:00:00Z · 7 bar"')
})

it('labels the plotted time extent separately from a truncated whole-file summary', () => {
  const html = renderToStaticMarkup(<SeriesChart series={series} filename="synthetic.csv" />)
  const labels = Array.from(html.matchAll(/<text[^>]*>(.*?)<\/text>/g), match => match[1])
  expect(labels).toContain('22 Sept 2026, 10:00:00 UTC')
  expect(labels).not.toContain('22 Sept 2026, 11:00:00 UTC')
  expect(html).toContain('<dd>22 Sept 2026, 11:00:00 UTC</dd>')
})

it('keeps a single original point readable and omits a selector for no points', () => {
  const one = renderToStaticMarkup(<SeriesChart series={{ ...series, points: series.points.slice(0, 1) }} filename="synthetic.csv" />)
  expect(one).toContain('Point 1 of 1:')
  const empty = renderToStaticMarkup(<SeriesChart series={{ ...series, points: [] }} filename="synthetic.csv" />)
  expect(empty).not.toContain('type="range"')
  expect(empty).toContain('no plottable points')
})

it('does not round selected values or discard timestamp precision and offsets', () => {
  const precise = { ...series, points: [{ time: '2026-09-22T11:00:00.123456+02:00', value: 7.123456789 }] }
  const html = renderToStaticMarkup(<SeriesChart series={precise} filename="synthetic.csv" />)
  expect(html).toContain('2026-09-22T11:00:00.123456+02:00 · 7.123456789 bar')
})

it('shows source-local timestamps verbatim, never labelled UTC, positioned without a zone shift', () => {
  const local: Series = {
    ...series,
    time_basis: 'source_local',
    points: [
      { time: '2026-03-29T01:30:00', value: 7 },
      { time: '2026-03-29T02:30:00', value: 9 }, // inside the Europe/Amsterdam DST gap
      { time: '2026-03-29T03:30:00', value: 11 },
    ],
    summary: { ...series.summary, start: '2026-03-29T01:30:00', end: '2026-03-29T03:30:00' },
  }
  const html = renderToStaticMarkup(<SeriesChart series={local} filename="local.csv" />)
  expect(html).toContain('Source-local time · timezone unknown')
  expect(html).toContain('2026-03-29T01:30:00</text>')
  expect(html).toContain('2026-03-29T03:30:00</text>')
  expect(html).not.toMatch(/\d UTC/) // no formatted UTC label anywhere; only the caveat mentions UTC
  expect(html).toContain('aria-valuetext="Point 1 of 3: 2026-03-29T01:30:00 · 7 bar"')
  // Equal one-hour steps stay equidistant: the middle point sits exactly halfway.
  const xs = [...html.matchAll(/[ML](\d+\.\d)/g)].map((m) => Number(m[1]))
  expect(xs).toHaveLength(3)
  expect(Math.abs((xs[0]! + xs[2]!) / 2 - xs[1]!)).toBeLessThan(0.11)
})
