import { LogOut } from 'lucide-react'
import type { Health, User } from '../api/types'
import { formatEur } from '../lib/format'
import { localeNames, useLocale } from '../lib/locale'

interface Props {
  user: User
  health: Health | null
  healthError: string | null
  onSignOut: () => void
}

/** Top bar: brand, honest backend status from GET /health, account. */
export function AppHeader({ user, health, healthError, onSignOut }: Props) {
  const { locale, setLocale, text } = useLocale()
  return (
    <header className="app-header">
      <span className="brand">Newton</span>
      <div className="health" role="status">
        {healthError && <span className="health-item health-bad">{text({ en: 'Server status unavailable', nl: 'Serverstatus niet beschikbaar' })}</span>}
        {health && (
          <>
            <span className={health.status === 'ok' ? 'health-item' : 'health-item health-bad'}>
              API {health.status}
            </span>
            <span className="health-item">DB {health.database}</span>
            <span className="health-item">Retrieval {health.retrieval}</span>
            <span className="health-item" title={text({ en: 'Model API budget for this local run', nl: 'Model-API-budget voor deze lokale run' })}>
              {text({ en: 'Budget', nl: 'Budget' })} {formatEur(health.budget.spent_eur)} / {formatEur(health.budget.ceiling_eur)}
            </span>
          </>
        )}
      </div>
      <span className="user-email" title={user.email}>
        {user.email}
      </span>
      <select
        className="locale-select"
        value={locale}
        onChange={(event) => setLocale(event.target.value as typeof locale)}
        aria-label={text({ en: 'Language', nl: 'Taal' })}
      >
        {Object.entries(localeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <button type="button" className="icon-btn icon-btn-dark" onClick={onSignOut} aria-label={text({ en: 'Sign out', nl: 'Afmelden' })}>
        <LogOut size={16} aria-hidden="true" />
      </button>
    </header>
  )
}
