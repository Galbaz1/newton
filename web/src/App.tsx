import { useEffect, useState } from 'react'
import { api } from './api/client'
import { ApiError, SESSION_EXPIRED_EVENT, errorMessage } from './api/http'
import type { User } from './api/types'
import { Notice, Spinner } from './components/ui'
import { AuthScreen } from './features/auth/AuthScreen'
import { Workspace } from './Workspace'
import { useLocale } from './lib/locale'

type SessionState =
  | { phase: 'checking' }
  | { phase: 'anonymous' }
  | { phase: 'unreachable'; message: string }
  | { phase: 'signed-in'; user: User }

/** Session bootstrap: GET /auth/me decides between sign-in and the workspace. */
export function App() {
  const { text } = useLocale()
  const [session, setSession] = useState<SessionState>({ phase: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setSession({ phase: 'checking' })
    api.me().then(
      (user) => !cancelled && setSession({ phase: 'signed-in', user }),
      (caught: unknown) => {
        if (cancelled) return
        // 401 is the normal signed-out answer; anything else is a real problem.
        if (caught instanceof ApiError && caught.status === 401) setSession({ phase: 'anonymous' })
        else setSession({ phase: 'unreachable', message: errorMessage(caught) })
      },
    )
    return () => {
      cancelled = true
    }
  }, [attempt])

  // An expired cookie mid-session returns the user to sign-in instead of a wall of errors.
  useEffect(() => {
    const onExpired = () => setSession({ phase: 'anonymous' })
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  if (session.phase === 'checking') {
    return (
      <main className="center-screen">
        <Spinner label={text({ en: 'Checking session…', nl: 'Sessie controleren…' })} />
      </main>
    )
  }
  if (session.phase === 'unreachable') {
    return (
      <main className="center-screen">
        <Notice tone="error" onRetry={() => setAttempt(attempt + 1)}>
          {session.message}
        </Notice>
      </main>
    )
  }
  if (session.phase === 'anonymous') {
    return <AuthScreen onAuthenticated={(user) => setSession({ phase: 'signed-in', user })} />
  }
  return <Workspace user={session.user} onSignedOut={() => setSession({ phase: 'anonymous' })} />
}
