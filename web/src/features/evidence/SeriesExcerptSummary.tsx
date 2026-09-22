import type { SeriesPoint } from '../../api/types'
import type { TimeBasis } from '../../lib/timeBasis'
import { formatNumber, formatUtc } from '../../lib/format'
import type { SeriesExcerpt } from '../../lib/seriesExcerpt'
import { formatObservation, SOURCE_LOCAL_LABEL } from '../../lib/timeBasis'

function PointList({ title, points, unit, basis }: { title: string; points: SeriesPoint[]; unit: string; basis: TimeBasis }) {
  if (points.length === 0) return null
  return (
    <div>
      <h4>{title}</h4>
      <ul className="series-points">
        {points.map((point) => (
          <li key={point.time}>
            <span>{formatObservation(point.time, basis, formatUtc)}</span>
            <span>
              {formatNumber(point.value)} {unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Readable view of the JSON summary the backend attaches to time-series
 * evidence. `compact` is the one-line form for evidence cards; the full form
 * is used in the inspector. Times retain their declared original clock basis.
 */
export function SeriesExcerptSummary({ data, compact = false }: { data: SeriesExcerpt; compact?: boolean }) {
  const unit = data.unit ?? ''
  const range = `${formatObservation(data.start, data.timeBasis, formatUtc)} → ${formatObservation(data.end, data.timeBasis, formatUtc)}`
  if (compact) {
    return (
      <span className="evidence-excerpt">
        {data.valueColumn ?? 'Series'}
        {unit ? ` [${unit}]` : ''}: {data.count ?? '—'} values, min {formatNumber(data.min)}, max{' '}
        {formatNumber(data.max)}, mean {formatNumber(data.mean)} · {range}
      </span>
    )
  }
  const stats = [
    ['Series', `${data.valueColumn ?? '—'}${unit ? ` [${unit}]` : ' (unit not provided)'}`],
    ['Accepted values', data.count === null ? '—' : String(data.count)],
    ['Min', `${formatNumber(data.min)} ${unit}`],
    ['Max', `${formatNumber(data.max)} ${unit}`],
    ['Mean', `${formatNumber(data.mean)} ${unit}`],
    ['Time range', range],
  ] as const
  return (
    <div className="series-excerpt">
      {data.timeBasis === 'source_local' && <p className="meta">{SOURCE_LOCAL_LABEL}</p>}
      <dl className="stats">
        {stats.map(([term, value]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <PointList title="First observations supplied to the model" points={data.first} unit={unit} basis={data.timeBasis} />
      <PointList title="Last observations supplied to the model" points={data.last} unit={unit} basis={data.timeBasis} />
      {data.truncated && (
        <p className="meta">The model saw a truncated point list; the statistics cover all values.</p>
      )}
      {data.calculation && <p className="meta">{data.calculation}</p>}
    </div>
  )
}
