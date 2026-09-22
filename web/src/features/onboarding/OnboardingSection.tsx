import { Rocket } from 'lucide-react'
import type { OnboardingRun } from '../../api/types'
import { Badge, Button, Notice, SectionHeader, Spinner } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { statusInfo } from './runStatus'
import { useLocale } from '../../lib/locale'

interface Props {
  runs: OnboardingRun[] | null
  loading: boolean
  error: string | null
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onRetry: () => void
}

/** Sidebar: the company's onboarding runs (newest first) and the entry point. */
export function OnboardingSection({ runs, loading, error, selectedId, onSelect, onNew, onRetry }: Props) {
  const { locale, text } = useLocale()
  return (
    <section className="side-section" aria-label="Onboarding">
      <SectionHeader
        title="Onboarding"
        aside={
          <Button onClick={onNew} aria-label={text({ en: 'Onboard company', nl: 'Bedrijf onboarden' })}>
            <Rocket size={13} aria-hidden="true" /> {text({ en: 'Onboard company', nl: 'Bedrijf onboarden' })}
          </Button>
        }
      />
      {error && (
        <Notice tone="error" onRetry={onRetry}>
          {error}
        </Notice>
      )}
      {!runs && loading && <Spinner label={text({ en: 'Loading runs…', nl: 'Runs laden…' })} />}
      {runs?.length === 0 && <p className="muted small">{text({ en: 'No onboarding run for this company yet.', nl: 'Nog geen onboarding-run voor dit bedrijf.' })}</p>}
      {runs && runs.length > 0 && (
        <ul className="pick-list">
          {runs.map((run, index) => {
            const status = statusInfo(run.status, locale)
            return (
              <li key={run.id}>
                <button
                  type="button"
                  className={run.id === selectedId ? 'pick pick-active' : 'pick'}
                  aria-current={run.id === selectedId ? 'true' : undefined}
                  onClick={() => onSelect(run.id)}
                >
                  <span className="pick-title">
                    {index === 0 ? text({ en: 'Latest run', nl: 'Laatste run' }) : text({ en: 'Run', nl: 'Run' })} · {run.website || text({ en: 'no website', nl: 'zonder website' })}{' '}
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </span>
                  <span className="pick-sub">
                    {formatDateTime(run.created_at)}
                    {run.data_class !== 'original' ? ` · ${run.data_class}` : ''}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
