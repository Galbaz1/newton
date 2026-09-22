import { useEffect, useRef } from 'react'
import { api } from '../../api/client'
import type { OnboardingRun } from '../../api/types'
import { useResource } from '../../lib/useResource'
import type { Resource } from '../../lib/useResource'
import { POLL_INTERVAL_MS, runActions, runChanged } from './runStatus'

/**
 * Loads one run and polls it every 2 seconds while the server reports
 * `running`. Calls `onChanged` whenever the projection moved, so the
 * workspace can refresh machine, source and readiness lists.
 */
export function useOnboardingRun(runId: string | null, onChanged: () => void): Resource<OnboardingRun> {
  const run = useResource(runId && `onboarding:${runId}`, (signal) => api.onboarding(runId!, signal))
  const previous = useRef<OnboardingRun | null>(null)
  const notify = useRef(onChanged)
  notify.current = onChanged

  useEffect(() => {
    if (run.data && runChanged(previous.current, run.data)) notify.current()
    previous.current = run.data
  }, [run.data])

  const active = run.data ? runActions(run.data.status).isActive : false
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => void run.reload(), POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [active, run.reload])

  return run
}
