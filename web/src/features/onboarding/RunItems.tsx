import { Eye } from 'lucide-react'
import type { OnboardingItem } from '../../api/types'
import { Badge, Button } from '../../components/ui'
import { itemTone, severityTone } from './runStatus'
import { useLocale } from '../../lib/locale'

interface Props {
  items: OnboardingItem[]
  /** Opens the created source in the inspector, when the item has one. */
  onInspectSource?: (sourceId: string) => void
}

/** Profile summary rendered as key/value rows; nested values are shown as JSON. */
function ProfileRows({ profile }: { profile: Record<string, unknown> }) {
  const keys = Object.keys(profile)
  if (keys.length === 0) return null
  return (
    <dl className="item-profile">
      {keys.map((key) => {
        const value = profile[key]
        const text = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
          ? String(value)
          : JSON.stringify(value)
        return (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{text}</dd>
          </div>
        )
      })}
    </dl>
  )
}

/** Per-file progress, findings, hashes and full messages for one run. */
export function RunItems({ items, onInspectSource }: Props) {
  const { locale, text } = useLocale()
  return (
    <section className="run-section" aria-label={text({ en: 'Files in this run', nl: 'Bestanden in deze run' })}>
      <h2>{text({ en: 'Files', nl: 'Bestanden' })} ({items.length})</h2>
      {items.length === 0 && <p className="muted small">{text({ en: 'No files in this run.', nl: 'Geen bestanden in deze run.' })}</p>}
      <ul className="card-list">
        {items.map((item) => {
          const tone = itemTone(item.status)
          return (
            <li key={item.id} className={`card card-${tone}`}>
              <div className="card-head">
                <span className="card-title" title={item.filename}>
                  {item.filename}
                </span>
                <Badge tone={tone}>{item.status.replaceAll('_', ' ')}</Badge>
              </div>
              <p className="meta">
                {item.kind} · {text({ en: 'class', nl: 'klasse' })} {item.data_class}
                {item.machine_id ? '' : ` · ${text({ en: 'company library', nl: 'bedrijfsbibliotheek' })}`}
              </p>
              <p className="meta hash" title={item.sha256}>
                SHA-256 {item.sha256}
              </p>
              <p className="meta">
                {typeof item.profile.row_count === 'number' && `${item.profile.row_count.toLocaleString(locale === 'nl' ? 'nl-NL' : 'en-US')} ${text({ en: 'measurement rows', nl: 'meetregels' })}`}
                {typeof item.profile.page_count === 'number' && `${item.profile.page_count} ${text({ en: 'pages', nl: 'pagina’s' })}`}
              </p>
              <details className="source-details">
                <summary>{text({ en: 'Source details and recorded observations', nl: 'Bronkenmerken en vastgelegde waarnemingen' })}</summary>
                <ProfileRows profile={item.profile} />
              </details>
              {item.findings.length > 0 && (
                <ul className="finding-list" aria-label={text({ en: `Findings for ${item.filename}`, nl: `Bevindingen voor ${item.filename}` })}>
                  {item.findings.map((finding, index) => (
                    <li key={`${finding.code}:${index}`} className={`finding finding-${severityTone(finding.severity)}`}>
                      <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
                      <span className="finding-code">{finding.code}</span>
                      <span className="finding-message">{finding.message}</span>
                    </li>
                  ))}
                </ul>
              )}
              {item.source_id && onInspectSource && (
                <div className="row">
                  <Button onClick={() => onInspectSource(item.source_id!)}>
                    <Eye size={14} aria-hidden="true" /> {text({ en: 'Inspect source', nl: 'Bron inspecteren' })}
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
