import type { SourceAnnotations } from '../../api/types'
import { Badge, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

/**
 * Parsed annotation intervals. Start/end/instant are shown exactly as the
 * source wrote them; the endpoint states no interval semantics, and absence of
 * an annotation in a period is not evidence that nothing happened.
 */
export function AnnotationTable({ data }: { data: SourceAnnotations }) {
  const { text } = useLocale()
  return (
    <section aria-label="Annotations" className="stack">
      <div className="row wrap">
        <Badge tone="neutral">{data.intervals.length} {text({ en: 'annotation interval(s)', nl: 'annotatie-interval(len)' })}</Badge>
        <span className="meta">{text({ en: 'semantics:', nl: 'semantiek:' })} {data.interval_semantics}</span>
      </div>
      <p className="meta hash" title={data.original_sha256}>
        {text({ en: 'Original', nl: 'Origineel' })} SHA-256 {data.original_sha256}
      </p>
      <Notice tone="warning">
        {text({ en: 'Intervals use the boundaries recorded by the source.', nl: 'Intervalgrenzen zijn overgenomen zoals de bron ze schreef.' })}
      </Notice>
      {data.findings.map((finding, index) => (
        <Notice key={`${finding.code}:${index}`} tone={finding.severity.toLowerCase() === 'error' ? 'error' : 'warning'}>
          {finding.code}: {finding.message}
        </Notice>
      ))}
      {data.intervals.length === 0 ? (
        <p className="muted small">{text({ en: 'No intervals were parsed from this source.', nl: 'Geen intervallen geparsed uit deze bron.' })}</p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption>{text({ en: 'Annotations from the source', nl: 'Annotaties uit de bron' })}</caption>
            <thead>
              <tr>
                <th scope="col">Label</th>
                <th scope="col">Object</th>
                <th scope="col">Start</th>
                <th scope="col">{text({ en: 'End', nl: 'Einde' })}</th>
                <th scope="col">{text({ en: 'Instant', nl: 'Moment' })}</th>
                <th scope="col">{text({ en: 'Task / annotation', nl: 'Taak / annotatie' })}</th>
              </tr>
            </thead>
            <tbody>
              {data.intervals.map((interval) => (
                <tr key={`${interval.task_id}:${interval.annotation_id}`}>
                  <td>{interval.label}</td>
                  <td>{interval.object_ref}</td>
                  <td>{interval.start ?? '—'}</td>
                  <td>{interval.end ?? '—'}</td>
                  <td>{interval.instant ?? '—'}</td>
                  <td>
                    {interval.task_id} / {interval.annotation_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
