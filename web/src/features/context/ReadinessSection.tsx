import type { Readiness } from '../../api/types'
import { Badge, Notice, SectionHeader, Spinner } from '../../components/ui'
import type { Tone } from '../../components/ui'
import { useLocale } from '../../lib/locale'

/**
 * Maps a server capability state onto a visual tone. Only `ready` is treated
 * as ready; unknown states stay neutral and show the server's own wording.
 */
function capabilityTone(state: string): Tone {
  if (state === 'ready') return 'ready'
  if (state === 'error') return 'error'
  if (state === 'missing' || state.startsWith('needs')) return 'missing'
  return 'neutral'
}

interface Props {
  readiness: Readiness | null
  loading: boolean
  error: string | null
  onRetry: () => void
}

/** What this machine's current inputs enable, as reported by the backend. */
export function ReadinessSection({ readiness, loading, error, onRetry }: Props) {
  const { text } = useLocale()
  return (
    <section className="side-section">
      <SectionHeader
        title={text({ en: 'Readiness', nl: 'Gereedheid' })}
        aside={readiness ? <span className="meta">{readiness.source_count} {text({ en: 'sources', nl: 'bronnen' })}</span> : null}
      />
      {error && (
        <Notice tone="error" onRetry={onRetry}>
          {error}
        </Notice>
      )}
      {!readiness && loading && <Spinner label={text({ en: 'Checking inputs…', nl: 'Invoer controleren…' })} />}
      {readiness && readiness.capabilities.length === 0 && (
        <p className="muted small">{text({ en: 'The server reported no capabilities for this machine.', nl: 'De server meldt geen mogelijkheden voor deze machine.' })}</p>
      )}
      {readiness && (
        <ul className="capabilities">
          {readiness.capabilities.map((capability) => {
            const tone = capabilityTone(capability.state)
            return (
              <li key={capability.id} className={`capability capability-${tone}`}>
                <div className="capability-head">
                  <span>{capability.label}</span>
                  <Badge tone={tone}>{capability.state.replaceAll('_', ' ')}</Badge>
                </div>
                {capability.reason && <p className="small muted">{capability.reason}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
