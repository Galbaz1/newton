import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { User } from '../../api/types'
import { Button, Field, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

type Mode = 'login' | 'register'

/** Sign-in and registration. A new account starts empty: no demo corpus. */
export function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const { text } = useLocale()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const call = mode === 'login' ? api.login : api.register
      onAuthenticated(await call(email.trim(), password))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth">
      <section className="auth-intro">
        <p className="brand">Newton</p>
        <h1>{text({ en: 'Investigate machines with inspectable evidence.', nl: 'Onderzoek machines met controleerbaar bewijs.' })}</h1>
        <ul>
          <li>{text({ en: 'Onboard a company and its machines in a private workspace.', nl: 'Breng een bedrijf en machines onder in een privéwerkruimte.' })}</li>
          <li>{text({ en: 'Add manuals, images, maintenance records and original time series.', nl: 'Voeg handleidingen, afbeeldingen, onderhoudsregistraties en originele tijdreeksen toe.' })}</li>
          <li>{text({ en: 'Ask questions and inspect the cited sources.', nl: 'Stel vragen en bekijk de aangehaalde bronnen.' })}</li>
        </ul>
        <p className="muted">
          {text({ en: 'New accounts start empty. Add the data you want to investigate.', nl: 'Nieuwe accounts beginnen leeg. Voeg de gegevens toe die je wilt onderzoeken.' })}
        </p>
      </section>

      <form className="auth-card" onSubmit={submit}>
        <div className="tabs" role="tablist" aria-label={text({ en: 'Account', nl: 'Account' })}>
          {(['login', 'register'] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              className={mode === value ? 'tab tab-active' : 'tab'}
              onClick={() => {
                setMode(value)
                setError(null)
              }}
            >
              {value === 'login' ? text({ en: 'Sign in', nl: 'Inloggen' }) : text({ en: 'Create account', nl: 'Account maken' })}
            </button>
          ))}
        </div>
        <Field label={text({ en: 'Email', nl: 'E-mail' })}>
          <input
            type="email"
            required
            maxLength={254}
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label={text({ en: 'Password', nl: 'Wachtwoord' })} hint={mode === 'register' ? text({ en: '12 to 200 characters.', nl: '12 tot 200 tekens.' }) : undefined}>
          <input
            type="password"
            required
            minLength={mode === 'register' ? 12 : 1}
            maxLength={200}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" variant="primary" busy={busy}>
          {mode === 'login' ? text({ en: 'Sign in', nl: 'Inloggen' }) : text({ en: 'Create account', nl: 'Account maken' })}
        </Button>
      </form>
    </main>
  )
}
