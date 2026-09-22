import { useMemo, useState } from 'react'
import type { PointerEvent } from 'react'
import type { Series } from '../../api/types'
import { Notice } from '../../components/ui'
import { formatNumber, formatUtc } from '../../lib/format'
import { SOURCE_LOCAL_LABEL, formatObservation, timeBasisOf } from '../../lib/timeBasis'
import { CHART, buildGeometry, nearest } from './chartGeometry'
import type { Plotted } from './chartGeometry'
import { useLocale } from '../../lib/locale'

/**
 * Original series values with a summary and native keyboard point inspection.
 * Axes describe the plotted extent; the summary can cover a larger source.
 */
export function SeriesChart({ series, filename }: { series: Series; filename: string }) {
  const { text } = useLocale()
  const basis = timeBasisOf(series.time_basis)
  const geometry = useMemo(() => buildGeometry(series.points, basis), [series.points, basis])
  // Source-local strings are shown exactly as written; absolute ones in UTC.
  const fmt = (time: string | null | undefined) => formatObservation(time, basis, formatUtc)
  const sourceLocalLabel = text({ en: 'Source-local time · timezone unknown', nl: SOURCE_LOCAL_LABEL })
  const basisNote = basis === 'source_local' ? sourceLocalLabel : text({ en: 'axes and summary in UTC', nl: 'assen en samenvatting in UTC' })
  const [hover, setHover] = useState<Plotted | null>(null)
  const [pointIndex, setPointIndex] = useState(0)
  const { summary } = series
  const unit = series.unit || text({ en: 'unit not provided', nl: 'eenheid niet opgegeven' })
  const selected = geometry?.plotted[pointIndex]
  const active = hover ?? selected
  const reading = (point: Plotted) => `${point.point.time} · ${point.point.value} ${unit}`

  function onMove(event: PointerEvent<SVGSVGElement>) {
    if (!geometry) return
    const box = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - box.left) / box.width) * CHART.width
    setHover(nearest(geometry.plotted, x))
  }

  const description =
    `${series.value_column} in ${unit} from ${filename}, ` +
    `${fmt(summary.start)} to ${fmt(summary.end)} (${basisNote}). ` +
    `${summary.count} accepted values, minimum ${formatNumber(summary.min)}, ` +
    `maximum ${formatNumber(summary.max)}, mean ${formatNumber(summary.mean)}.`

  return (
    <figure className="chart">
      {series.truncated && (
        <Notice tone="warning">
          Showing {series.points.length} original points (server limit). The summary below covers all{' '}
          {summary.count} accepted values.
        </Notice>
      )}
      {geometry ? (
        <svg
          viewBox={`0 0 ${CHART.width} ${CHART.height}`}
          role="img"
          aria-label={description}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {geometry.yTicks.map((tick) => (
            <g key={tick.y}>
              <line className="chart-grid" x1={CHART.left} x2={CHART.width - CHART.right} y1={tick.y} y2={tick.y} />
              <text className="chart-label" x={CHART.left - 6} y={tick.y + 3.5} textAnchor="end">
                {formatNumber(tick.value)}
              </text>
            </g>
          ))}
          <text className="chart-label" x={CHART.left} y={CHART.height - 8}>
            {fmt(geometry.start)}
          </text>
          <text className="chart-label" x={CHART.width - CHART.right} y={CHART.height - 8} textAnchor="end">
            {fmt(geometry.end)}
          </text>
          <path className="chart-line" d={geometry.path} />
          {geometry.plotted.length === 1 && geometry.plotted[0] && (
            <circle className="chart-dot" cx={geometry.plotted[0].x} cy={geometry.plotted[0].y} r={3.5} />
          )}
          {active && (
            <g>
              <line className="chart-cursor" x1={active.x} x2={active.x} y1={CHART.top} y2={CHART.height - CHART.bottom} />
              <circle className="chart-dot" cx={active.x} cy={active.y} r={3.5} />
            </g>
          )}
        </svg>
      ) : (
        <Notice tone="info">The server returned no plottable points for this series.</Notice>
      )}
      {geometry && selected && (
        <label className="chart-point-control">
          {text({ en: 'Inspect original point', nl: 'Origineel punt bekijken' })} · {pointIndex + 1} {text({ en: 'of', nl: 'van' })} {geometry.plotted.length}
          <input type="range" min={0} max={geometry.plotted.length - 1} step={1}
            value={pointIndex} aria-label={text({ en: 'Inspect original point', nl: 'Origineel punt bekijken' })}
            aria-valuetext={`${text({ en: 'Point', nl: 'Punt' })} ${pointIndex + 1} ${text({ en: 'of', nl: 'van' })} ${geometry.plotted.length}: ${reading(selected)}`}
            onChange={(event) => { setPointIndex(Number(event.target.value)); setHover(null) }} />
          <span className="meta">{text({ en: 'Use arrow keys, Home or End, or move over the chart.', nl: 'Gebruik de pijltjestoetsen, Home of End, of beweeg over de grafiek.' })}</span>
        </label>
      )}
      {active && <p className="chart-readout" aria-live="off">{reading(active)}</p>}
      {basis === 'source_local' && (
        <Notice tone="warning">
          {sourceLocalLabel}: {text({ en: 'timestamps have no offset and are shown as recorded.', nl: 'tijdstempels hebben geen offset en worden getoond zoals vastgelegd.' })}
        </Notice>
      )}
      <figcaption>
        <strong>
          {series.value_column} [{unit}]
        </strong>{' '}
        {text({ en: 'over', nl: 'over' })} {series.time_column} ({basisNote}) · {text({ en: 'source:', nl: 'bron:' })} {filename}
      </figcaption>
      <dl className="stats">
        {(
          [
            ['Accepted values', String(summary.count)],
            ['Min', `${formatNumber(summary.min)} ${series.unit}`],
            ['Max', `${formatNumber(summary.max)} ${series.unit}`],
            ['Mean', `${formatNumber(summary.mean)} ${series.unit}`],
            ['Start', fmt(summary.start)],
            ['End', fmt(summary.end)],
          ] as const
        ).map(([term, value]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </figure>
  )
}
