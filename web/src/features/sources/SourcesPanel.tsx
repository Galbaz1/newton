import type { Source } from '../../api/types'
import { EmptyState, Notice, SectionHeader, Spinner } from '../../components/ui'
import { SourceCard } from './SourceCard'
import { UploadForm } from './UploadForm'
import { useLocale } from '../../lib/locale'

interface Props {
  machineId: string
  sources: Source[] | null
  loading: boolean
  error: string | null
  onInspect: (source: Source) => void
  /** Any upload, mapping, revision or delete changes the machine context. */
  onChanged: () => void
}

/** Source intake and the list of everything this machine's answers may cite. */
export function SourcesPanel(props: Props) {
  const { text } = useLocale()
  const { machineId, sources, loading, error, onInspect, onChanged } = props
  return (
    <section className="sources">
      <SectionHeader
        title={text({ en: 'Sources', nl: 'Bronnen' })}
        aside={sources ? <span className="meta">{sources.length} {text({ en: 'uploaded', nl: 'geüpload' })}</span> : null}
      />
      <UploadForm machineId={machineId} onUploaded={onChanged} />
      {error && (
        <Notice tone="error" onRetry={onChanged}>
          {error}
        </Notice>
      )}
      {!sources && loading && <Spinner label={text({ en: 'Loading sources…', nl: 'Bronnen laden…' })} />}
      {sources?.length === 0 && (
        <EmptyState title={text({ en: 'No sources yet', nl: 'Nog geen bronnen' })}>
          {text({ en: 'Upload manuals, photos, maintenance records or CSV measurements for this machine.', nl: 'Upload handleidingen, foto’s, onderhoudsregistraties of CSV-metingen voor deze machine.' })}
        </EmptyState>
      )}
      {sources && sources.length > 0 && (
        <ul className="card-list">
          {sources.map((source) => (
            <SourceCard
              key={`${source.id}:${source.version}`}
              source={source}
              onInspect={onInspect}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
