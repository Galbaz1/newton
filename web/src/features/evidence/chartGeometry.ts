import type { SeriesPoint } from '../../api/types'
import { seriesTimeMs } from '../../lib/timeBasis'
import type { TimeBasis } from '../../lib/timeBasis'

export interface Plotted {
  x: number
  y: number
  point: SeriesPoint
}

export interface Geometry {
  plotted: Plotted[]
  path: string
  yTicks: { y: number; value: number }[]
  yMin: number
  yMax: number
  start: string
  end: string
}

export const CHART = { width: 640, height: 260, left: 58, right: 14, top: 14, bottom: 30 }

/**
 * Projects original points onto the SVG plane. Values are only positioned,
 * never smoothed, resampled or interpolated; points with unparseable times
 * are skipped from the drawing and counted by the caller. Source-local times
 * are positioned by their components only (never through the browser zone).
 */
export function buildGeometry(points: SeriesPoint[], basis: TimeBasis = 'absolute'): Geometry | null {
  const timed = points
    .map((point) => ({ point, t: seriesTimeMs(point.time, basis) }))
    .filter((item) => Number.isFinite(item.t) && Number.isFinite(item.point.value))
  if (timed.length === 0) return null

  let tMin = Infinity
  let tMax = -Infinity
  let yMin = Infinity
  let yMax = -Infinity
  // Axis labels keep the original strings of the extreme points (no re-serialisation).
  let first = timed[0]!.point.time
  let last = timed[0]!.point.time
  for (const { t, point } of timed) {
    if (t < tMin) { tMin = t; first = point.time }
    if (t > tMax) { tMax = t; last = point.time }
    yMin = Math.min(yMin, point.value)
    yMax = Math.max(yMax, point.value)
  }
  // A flat series still needs a visible band around its single value.
  if (yMin === yMax) {
    const pad = Math.abs(yMin) * 0.05 || 1
    yMin -= pad
    yMax += pad
  }
  const innerW = CHART.width - CHART.left - CHART.right
  const innerH = CHART.height - CHART.top - CHART.bottom
  const tSpan = tMax - tMin || 1

  const plotted = timed.map(({ t, point }) => ({
    x: CHART.left + ((t - tMin) / tSpan) * innerW,
    y: CHART.top + (1 - (point.value - yMin) / (yMax - yMin)) * innerH,
    point,
  }))
  const path = plotted
    .map((p, index) => `${index === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join('')
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    y: CHART.top + (1 - fraction) * innerH,
    value: yMin + fraction * (yMax - yMin),
  }))
  return { plotted, path, yTicks, yMin, yMax, start: first, end: last }
}

/** Nearest plotted point to an x coordinate in SVG units. */
export function nearest(plotted: Plotted[], x: number): Plotted | null {
  let best: Plotted | null = null
  for (const candidate of plotted) {
    if (!best || Math.abs(candidate.x - x) < Math.abs(best.x - x)) best = candidate
  }
  return best
}
