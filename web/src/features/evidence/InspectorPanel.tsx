import { Download, X } from 'lucide-react'
import { useState } from 'react'
import { api, resourceUrl } from '../../api/client'
import { safeApiUrl } from '../../api/http'
import type { SeriesQuery, Source } from '../../api/types'
import { Badge, Notice, Spinner } from '../../components/ui'
import { parseSeriesExcerpt } from '../../lib/seriesExcerpt'
import { useResource } from '../../lib/useResource'
import { KIND_LABEL } from '../sources/sourceStatus'
import { PageViewer } from './PageViewer'
import { EvidenceProvenance } from './EvidenceProvenance'
import { SeriesChart } from './SeriesChart'
import { AnnotationTable } from './AnnotationTable'
import { SeriesControls } from './SeriesControls'
import { timeBasisOf } from '../../lib/timeBasis'
import { SeriesExcerptSummary } from './SeriesExcerptSummary'
import type { InspectTarget } from './inspectTarget'
import { useLocale } from '../../lib/locale'

interface Props {
  target: InspectTarget
  /** Current sources, to tell the reader when cited material has since changed. */
  sources: Source[] | null
  onClose: () => void
}

/** Evidence and source inspection: provenance, excerpt, pages or original series. */
export function InspectorPanel({ target, sources, onClose }: Props) {
  const { text } = useLocale()
  const current = sources?.find((source) => source.id === target.sourceId) ?? null
  const deleted = sources !== null && current === null
  const changed = current !== null && current.version !== target.version
  // Time-series evidence stores a JSON summary; show it readably, never edit it.
  const seriesExcerpt =
    target.kind === 'timeseries' && target.citation ? parseSeriesExcerpt(target.citation.excerpt) : null

  return (
    <section className="inspector" aria-label={text({ en: 'Evidence inspector', nl: 'Bewijsinspecteur' })}>
      <div className="inspector-head">
        <div>
          <p className="meta">
            {target.citation ? `${text({ en: 'Evidence', nl: 'Bewijs' })} ${target.citation.label}` : text({ en: 'Source', nl: 'Bron' })} ·{' '}
            {KIND_LABEL[target.kind] ?? target.kind}
          </p>
          <h2 title={target.filename}>{target.filename}</h2>
          <p className="meta">
            {text({ en: 'Revision', nl: 'Revisie' })} {target.revision || text({ en: 'not labelled', nl: 'niet gelabeld' })} · {text({ en: 'source version', nl: 'bronversie' })} {target.version}
            {target.citation?.page ? ` · ${text({ en: 'page', nl: 'pagina' })} ${target.citation.page}` : ''}
          </p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={text({ en: 'Close inspector', nl: 'Inspector sluiten' })}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      {deleted && (
        <Notice tone="warning">
          {text({ en: 'This source has been deleted. The original is no longer available here.', nl: 'Deze bron is verwijderd. Het origineel is hier niet meer beschikbaar.' })}
        </Notice>
      )}
      {changed && (
        <Notice tone="warning">
          {text({ en: `Cited at source version ${target.version}; the current version is ${current.version}.`, nl: `Aangehaald bij bronversie ${target.version}; de huidige versie is ${current.version}.` })}
        </Notice>
      )}

      {target.citation && (
        <blockquote className="excerpt">
          <Badge tone="neutral">{seriesExcerpt ? text({ en: 'Cited series summary', nl: 'Aangehaalde tijdreekssamenvatting' }) : text({ en: 'Cited excerpt', nl: 'Aangehaald fragment' })}</Badge>
          {seriesExcerpt ? (
            <SeriesExcerptSummary data={seriesExcerpt} />
          ) : (
            <p>{target.citation.excerpt || text({ en: 'The server provided no excerpt for this citation.', nl: 'De server gaf geen fragment voor deze verwijzing.' })}</p>
          )}
        </blockquote>
      )}

      {current?.metadata.evidence_caveats && current.metadata.evidence_caveats.length > 0 && (
        <section className="evidence-caveats" aria-label={text({ en: 'Evidence notes', nl: 'Kanttekeningen bij dit bewijs' })}>
          <Notice tone="warning">
            <strong>{text({ en: 'Evidence notes', nl: 'Kanttekeningen bij dit bewijs' })}</strong>
            <ul className="limitation-list">
              {current.metadata.evidence_caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
            <span className="small">
              {text({ en: 'Document values are claims from that document. A time series provides original values.', nl: 'Getallen in documenten zijn beweringen uit dat document. Een meetreeks levert originele waarden.' })}
            </span>
          </Notice>
        </section>
      )}
      {target.evidence && <EvidenceProvenance evidence={target.evidence} />}

      {!deleted && (
        <>
          <a className="btn btn-secondary" href={resourceUrl.original(target.sourceId)} download>
            <Download size={14} aria-hidden="true" /> {text({ en: 'Download original', nl: 'Origineel downloaden' })}
          </a>
          {target.kind === 'timeseries' ? (
            <SeriesView target={target} current={current} />
          ) : target.kind === 'annotation' ? (
            <AnnotationView sourceId={target.sourceId} />
          ) : (
            <PageViewer sourceId={target.sourceId} initialPage={target.citation?.page ?? null} />
          )}
        </>
      )}
    </section>
  )
}

function SeriesView({ target, current }: { target: InspectTarget; current: Source | null }) {
  const { text } = useLocale()
  const unmapped = current?.status === 'needs_mapping'
  const quarantined = current?.status === 'quarantined'
  const [query, setQuery] = useState<SeriesQuery>({})
  const channels = current?.metadata.channels ?? []
  const url = safeApiUrl(target.seriesUrl)
  // A cited series URL is exact evidence; channel/period controls query the current source.
  const useCitedUrl = url !== null && !query.channel && !query.start && !query.end
  const queryKey = `${query.channel ?? ''}|${query.start ?? ''}|${query.end ?? ''}`
  const series = useResource(
    unmapped || quarantined ? null : `series:${target.sourceId}:${current?.version ?? ''}:${queryKey}`,
    (signal) => (useCitedUrl ? api.seriesByUrl(url, signal) : api.series(target.sourceId, signal, query)),
  )

  if (quarantined) {
    return (
      <Notice tone="warning">
        {text({ en: 'This source is quarantined. Charts and calculations are unavailable.', nl: 'Deze bron staat in quarantaine. Grafieken en berekeningen zijn niet beschikbaar.' })}
      </Notice>
    )
  }
  if (unmapped) {
    return (
      <Notice tone="info">
        {text({ en: 'This CSV needs a column mapping before it can be charted.', nl: 'Deze CSV heeft een kolomkoppeling nodig voordat hij kan worden getoond.' })}
      </Notice>
    )
  }
  return (
    <>
      <SeriesControls channels={channels} value={query} onChange={setQuery} basis={timeBasisOf(current?.metadata.time_basis)} />
      {series.error && (
        <Notice tone="error" onRetry={() => void series.reload()}>
          {series.error}
        </Notice>
      )}
      {!series.error && !series.data && <Spinner label={text({ en: 'Loading original series…', nl: 'Originele tijdreeks laden…' })} />}
      {series.data && (
        <SeriesChart
          key={`${target.sourceId}:${current?.version ?? target.version}:${queryKey}`}
          series={series.data}
          filename={target.filename}
        />
      )}
    </>
  )
}

/** Parsed annotation intervals as a table, with the endpoint's own caveats. */
function AnnotationView({ sourceId }: { sourceId: string }) {
  const { text } = useLocale()
  const annotations = useResource(`annotations:${sourceId}`, (signal) => api.annotations(sourceId, signal))
  if (annotations.error) {
    return (
      <Notice tone="error" onRetry={() => void annotations.reload()}>
        {annotations.error}
      </Notice>
    )
  }
  if (annotations.data === null) return <Spinner label={text({ en: 'Loading annotations…', nl: 'Annotaties laden…' })} />
  return <AnnotationTable data={annotations.data} />
}
