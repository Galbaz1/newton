import type { OnboardingQuestion, OnboardingRun, OnboardingStatus } from '../../api/types'
import type { Tone } from '../../components/ui'
import type { Locale } from '../../lib/locale'

export function statusInfo(status: string, locale: Locale = 'en'): { label: string; tone: Tone; explain: string } {
  const text = (en: string, nl: string) => locale === 'nl' ? nl : en
  const statuses: Record<OnboardingStatus, { label: string; tone: Tone; explain: string }> = {
  draft: {
    label: text('Draft', 'Concept'),
    tone: 'neutral',
    explain: text('Add files, then start the run.', 'Bestanden kunnen nog worden toegevoegd. Start de run om het onderzoek te beginnen.'),
  },
  running: {
    label: text('Running', 'Bezig'),
    tone: 'ready',
    explain: text('Newton is processing the sources.', 'Newton onderzoekt de bronnen.'),
  },
  paused: {
    label: text('Paused', 'Gepauzeerd'),
    tone: 'missing',
    explain: text('The run is paused.', 'De run is gepauzeerd.'),
  },
  completed: { label: text('Completed', 'Voltooid'), tone: 'ready', explain: text('The run is complete.', 'De run is afgerond.') },
  completed_with_warnings: {
    label: text('Completed with warnings', 'Voltooid met waarschuwingen'),
    tone: 'missing',
    explain: text('Review the findings and open questions.', 'Lees de bevindingen en openstaande vragen.'),
  },
  error: {
    label: text('Error', 'Fout'),
    tone: 'error',
    explain: text('The run stopped with an error. Review the log before resuming.', 'De run is gestopt met een fout. Bekijk het logboek voordat je hervat.'),
  },
  }
  return (
    statuses[status as OnboardingStatus] ?? {
      label: status,
      tone: 'neutral',
      explain: text('The server reported an unknown status.', 'De server meldde een onbekende status.'),
    }
  )
}

/** Which controls the contract allows for a run in this status. */
export function runActions(status: OnboardingStatus | string) {
  return {
    canStart: status === 'draft',
    /** Pause is a boundary request: the worker finishes its current step first. */
    canPause: status === 'running',
    canResume: status === 'paused' || status === 'error' || status === 'completed_with_warnings',
    /** Never while running or after completion; a finishing worker may still answer 409. */
    canUpload: status === 'draft' || status === 'paused' || status === 'error',
    /** Poll GET /onboarding/{id} every 2 seconds only while the server works. */
    isActive: status === 'running',
  }
}

export const POLL_INTERVAL_MS = 2000

/** Persistent banner text for non-original runs; null for original data. */
export function dataClassBanner(dataClass: string, locale: Locale = 'en'): string | null {
  if (dataClass === 'synthetic') {
    return locale === 'nl' ? 'Synthetische gegevens. Deze run gebruikt kunstmatige bronnen.' : 'Synthetic data. This run uses artificial sources.'
  }
  if (dataClass === 'demo') {
    return locale === 'nl' ? 'Demogegevens. Deze run gebruikt demonstratiebronnen.' : 'Demo data. This run uses demonstration sources.'
  }
  return null
}

/** Whether a starter question can open an investigation right now. */
export function questionReady(question: OnboardingQuestion): boolean {
  return question.state === 'ready' && question.machine_id !== null
}

/** Clarifications the owner still has to answer. */
export function openClarifications(run: OnboardingRun) {
  return run.pending_questions.filter((question) => !question.answer)
}

/** Changes that require refreshing machine, source and readiness lists. */
export function runChanged(previous: OnboardingRun | null, next: OnboardingRun): boolean {
  if (!previous) return false
  return (
    previous.updated_at !== next.updated_at ||
    previous.status !== next.status ||
    previous.items.length !== next.items.length
  )
}

/** Human severity label and tone for findings and item states. */
export function severityTone(severity: string): Tone {
  const lower = severity.toLowerCase()
  if (lower === 'error' || lower === 'critical' || lower === 'quarantine') return 'error'
  if (lower === 'warning' || lower === 'warn') return 'missing'
  return 'neutral'
}

export function itemTone(status: string): Tone {
  const lower = status.toLowerCase()
  if (lower === 'ready' || lower === 'done' || lower === 'completed') return 'ready'
  if (lower === 'error' || lower === 'quarantined' || lower === 'failed') return 'error'
  if (lower === 'pending' || lower === 'uploaded' || lower === 'queued') return 'neutral'
  return 'missing'
}
