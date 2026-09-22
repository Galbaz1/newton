import { Download, Eye, FileText, Image as ImageIcon, LineChart, Tags, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, resourceUrl } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Source } from '../../api/types'
import { Badge, Button, Notice } from '../../components/ui'
import { formatDateTime, shortHash } from '../../lib/format'
import { MappingForm } from './MappingForm'
import { DATA_CLASS_LABEL, KIND_LABEL, statusInfo } from './sourceStatus'
import { useLocale } from '../../lib/locale'

const kindIcons = { document: FileText, image: ImageIcon, timeseries: LineChart, annotation: Tags }

interface Props {
  source: Source
  onInspect: (source: Source) => void
  /** Called after any successful PATCH or DELETE; the workspace refetches. */
  onChanged: () => void
}

/** One uploaded source: state, provenance and its correction actions. */
export function SourceCard({ source, onInspect, onChanged }: Props) {
  const { locale, text } = useLocale()
  const [panel, setPanel] = useState<'none' | 'mapping' | 'revision'>(
    source.status === 'needs_mapping' ? 'mapping' : 'none',
  )
  const [revision, setRevision] = useState(source.revision)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const info = statusInfo(source, locale)
  const Icon = kindIcons[source.kind] ?? FileText
  const warnings = source.metadata.warnings ?? []
  const channels = source.metadata.channels ?? []
  const findings = source.metadata.findings ?? []

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setPanel('none')
      onChanged()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  function saveRevision(event: FormEvent) {
    event.preventDefault()
    void run(() => api.updateSource(source.id, { revision: revision.trim() }))
  }

  function remove() {
    const question = text({ en: `Delete “${source.filename}”? The stored original and its metadata are removed.`, nl: `“${source.filename}” verwijderen? Het opgeslagen origineel en de metadata worden verwijderd.` })
    if (window.confirm(question)) void run(() => api.deleteSource(source.id))
  }

  const toggle = (next: 'mapping' | 'revision') => setPanel(panel === next ? 'none' : next)

  return (
    <li className={`card source-card card-${info.tone}`}>
      <div className="card-head">
        <Icon size={16} aria-hidden="true" />
        <span className="card-title" title={source.filename}>
          {source.filename}
        </span>
        <Badge tone={info.tone}>{info.label}</Badge>
      </div>
      <p className="meta">
        {KIND_LABEL[source.kind] ?? source.kind} · {text({ en: 'revision', nl: 'revisie' })} {source.revision || text({ en: 'not labelled', nl: 'niet gelabeld' })} · v
        {source.version} · {formatDateTime(source.created_at)}
        {source.machine_id === null ? ` · ${text({ en: 'company library', nl: 'bedrijfsbibliotheek' })}` : ''}
      </p>
      {source.data_class && source.data_class !== 'original' && (
        <Badge tone={source.data_class === 'derived' ? 'neutral' : 'missing'}>
          {DATA_CLASS_LABEL[source.data_class] ?? source.data_class} {text({ en: 'data', nl: 'gegevens' })}
        </Badge>
      )}
      <p className="small">{info.explain(source)}</p>
      {channels.length > 0 && (
        <p className="meta">
          {text({ en: 'Channels:', nl: 'Kanalen:' })}{' '}
          {channels
            .map((channel) => {
              const unit = channel.unit || text({ en: 'unit not provided', nl: 'eenheid niet opgegeven' })
              const support = channel.unit_support ? ` (${text({ en: 'unit from p.', nl: 'eenheid van p.' })} ${channel.unit_support.page})` : ''
              return `${channel.label || channel.column} [${unit}]${support}`
            })
            .join(', ')}
        </p>
      )}
      {findings.length > 0 && (
        <ul className="finding-list" aria-label={text({ en: `Findings for ${source.filename}`, nl: `Bevindingen voor ${source.filename}` })}>
          {findings.map((finding, index) => (
            <li key={`${finding.code}:${index}`} className="finding">
              <Badge tone={finding.severity.toLowerCase() === 'error' ? 'error' : finding.severity.toLowerCase() === 'info' ? 'neutral' : 'missing'}>
                {finding.severity}
              </Badge>
              <span className="finding-code">{finding.code}</span>
              <span className="finding-message">{finding.message}</span>
            </li>
          ))}
        </ul>
      )}
      {source.mapping && (
        <p className="meta">
          {text({ en: 'Mapped:', nl: 'Gekoppeld:' })} {source.mapping.time_column} → {source.mapping.value_column} [{source.mapping.unit}]
          {source.mapping.timezone ? ` · ${source.mapping.timezone}` : ''}
        </p>
      )}
      {warnings.map((warning) => (
        <Notice key={warning} tone="warning">
          {warning}
        </Notice>
      ))}
      <p className="meta hash" title={source.sha256}>
        SHA-256 {source.status === 'quarantined' ? source.sha256 : shortHash(source.sha256)}
      </p>

      <div className="row wrap">
        <Button onClick={() => onInspect(source)}>
          <Eye size={14} aria-hidden="true" /> {text({ en: 'Inspect', nl: 'Bekijken' })}
        </Button>
        {source.kind === 'timeseries' && (
          <Button onClick={() => toggle('mapping')} aria-expanded={panel === 'mapping'}>
            {source.mapping ? text({ en: 'Correct mapping', nl: 'Koppeling corrigeren' }) : text({ en: 'Map columns', nl: 'Kolommen koppelen' })}
          </Button>
        )}
        <Button onClick={() => toggle('revision')} aria-expanded={panel === 'revision'}>
          {text({ en: 'Correct revision', nl: 'Revisie corrigeren' })}
        </Button>
        <a className="btn btn-ghost" href={resourceUrl.original(source.id)} download>
          <Download size={14} aria-hidden="true" /> {text({ en: 'Original', nl: 'Origineel' })}
        </a>
        <Button variant="danger" onClick={remove} busy={busy} aria-label={text({ en: `Delete ${source.filename}`, nl: `${source.filename} verwijderen` })}>
          <Trash2 size={14} aria-hidden="true" />
        </Button>
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {panel === 'mapping' && (
        <MappingForm
          source={source}
          onSaved={() => {
            setPanel('none')
            onChanged()
          }}
        />
      )}
      {panel === 'revision' && (
        <form className="row" onSubmit={saveRevision}>
          <input
            aria-label={text({ en: 'Revision label', nl: 'Revisielabel' })}
            maxLength={200}
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
          />
          <Button type="submit" variant="primary" busy={busy}>
            {text({ en: 'Save', nl: 'Opslaan' })}
          </Button>
        </form>
      )}
    </li>
  )
}
