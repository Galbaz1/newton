import { Pause, Play, RefreshCw, Upload } from 'lucide-react'
import { useState } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { OnboardingQuestion, OnboardingRun } from '../../api/types'
import { Badge, Button, Notice, Spinner } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import type { Resource } from '../../lib/useResource'
import { Clarifications } from './Clarifications'
import { RunEvents } from './RunEvents'
import { RunItems } from './RunItems'
import { RunProfile } from './RunProfile'
import { StarterQuestions } from './StarterQuestions'
import { UploadList } from './UploadList'
import { dataClassBanner, runActions, statusInfo } from './runStatus'
import { ONBOARDING_ACCEPT, toEntries, uploadSequentially } from './uploadQueue'
import type { UploadEntry } from './uploadQueue'
import { useLocale } from '../../lib/locale'

interface Props {
  run: Resource<OnboardingRun>
  companyName: string | null
  onOpenQuestion: (question: OnboardingQuestion) => Promise<void>
  onInspectSource: (sourceId: string) => void
}

/** One onboarding run: status, controls, profile, files, clarifications, questions, log. */
export function OnboardingRunView({ run, companyName, onOpenQuestion, onInspectSource }: Props) {
  const { locale, text } = useLocale()
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'start' | 'pause' | 'resume' | null>(null)
  const [questionBusy, setQuestionBusy] = useState<string | null>(null)
  const data = run.data

  if (run.error && !data) {
    return (
      <Notice tone="error" onRetry={() => void run.reload()}>
        {run.error}
      </Notice>
    )
  }
  if (!data) return <Spinner label={text({ en: 'Loading run…', nl: 'Run laden…' })} />

  const status = statusInfo(data.status, locale)
  const actions = runActions(data.status)
  const banner = dataClassBanner(data.data_class, locale)

  async function act(kind: 'start' | 'pause' | 'resume', call: () => Promise<OnboardingRun>) {
    setBusy(kind)
    setActionError(null)
    try {
      run.setData(await call())
    } catch (caught) {
      setActionError(errorMessage(caught))
    } finally {
      setBusy(null)
    }
  }

  async function openQuestion(question: OnboardingQuestion) {
    setQuestionBusy(question.id)
    setActionError(null)
    try {
      await onOpenQuestion(question)
    } catch (caught) {
      setActionError(errorMessage(caught))
    } finally {
      setQuestionBusy(null)
    }
  }

  return (
    <div className="onboarding-run">
      {banner && (
        <div className="data-class-banner" role="alert">
          {banner}
        </div>
      )}
      <header className="run-head">
        <div>
          <p className="meta">{text({ en: 'Onboarding', nl: 'Onboarding' })}{companyName ? ` · ${companyName}` : ''}</p>
          <h2 className="onboarding-title">
            {data.website || text({ en: 'No website', nl: 'Zonder website' })} <Badge tone={status.tone}>{status.label}</Badge>
          </h2>
          <p className="meta">
            {text({ en: 'Stage:', nl: 'Fase:' })} {data.stage || '—'} · {text({ en: 'created', nl: 'aangemaakt' })} {formatDateTime(data.created_at)} · {text({ en: 'updated', nl: 'bijgewerkt' })}{' '}
            {formatDateTime(data.updated_at)}
          </p>
        </div>
        <div className="row wrap run-controls" aria-label={text({ en: 'Run controls', nl: 'Run-bediening' })}>
          {actions.canStart && (
            <Button variant="primary" busy={busy === 'start'} onClick={() => void act('start', () => api.startOnboarding(data.id))}>
              <Play size={14} aria-hidden="true" /> {text({ en: 'Start', nl: 'Starten' })}
            </Button>
          )}
          {actions.canPause && (
            <Button busy={busy === 'pause'} onClick={() => void act('pause', () => api.pauseOnboarding(data.id))}>
              <Pause size={14} aria-hidden="true" /> {text({ en: 'Pause', nl: 'Pauzeren' })}
            </Button>
          )}
          {actions.canResume && (
            <Button variant="primary" busy={busy === 'resume'} onClick={() => void act('resume', () => api.resumeOnboarding(data.id))}>
              <Play size={14} aria-hidden="true" /> {text({ en: 'Resume', nl: 'Hervatten' })}
            </Button>
          )}
          <Button variant="ghost" onClick={() => void run.reload()} aria-label={text({ en: 'Refresh run', nl: 'Run vernieuwen' })}>
            <RefreshCw size={14} aria-hidden="true" /> {text({ en: 'Refresh', nl: 'Vernieuwen' })}
          </Button>
        </div>
      </header>
      <p className="small">{status.explain}</p>
      {data.summary && <p className="run-summary">{data.summary}</p>}
      {actions.isActive && <Spinner label={text({ en: 'Newton is processing the run…', nl: 'Newton verwerkt de run…' })} />}
      {actionError && <Notice tone="error">{actionError}</Notice>}
      {run.error && <Notice tone="error">{run.error}</Notice>}

      {actions.canUpload && <RunFileUpload runId={data.id} onUploaded={() => void run.reload()} />}
      <Clarifications runId={data.id} questions={data.pending_questions} onAnswered={run.setData} />
      {data.reviews && data.reviews.length > 0 && (
        <section aria-label={text({ en: 'Independent review', nl: 'Onafhankelijke controle' })} className="panel">
          <h2>{text({ en: 'Independent review', nl: 'Onafhankelijke controle' })}</h2>
          {data.reviews.map((review, index) => (
            <div key={index}>
              <p className="meta">{review.model} · {review.effort} · {review.role === 'critical_verifier' ? text({ en: 'Critical contradiction', nl: 'Cruciale tegenstrijdigheid' }) : text({ en: 'Processing review', nl: 'Controle van de verwerking' })}</p>
              <p>{review.summary}</p>
              {review.findings.map((finding, number) => (
                <details key={number}>
                  <summary>{finding.reason}</summary>
                  <p className="meta">{text({ en: 'Related result:', nl: 'Betrokken resultaat:' })} {finding.target_id}</p>
                  <p className="meta">{text({ en: 'Evidence references:', nl: 'Bronverwijzingen:' })} {finding.evidence_ids.join(', ')}</p>
                </details>
              ))}
            </div>
          ))}
        </section>
      )}
      <StarterQuestions questions={data.questions} onOpen={(q) => void openQuestion(q)} busyId={questionBusy} />
      <RunProfile profile={data.profile} />
      <RunItems items={data.items} onInspectSource={onInspectSource} />
      <RunEvents events={data.events} items={data.items} />
    </div>
  )
}

/** Adds originals to a run that is not running; each file is its own request. */
function RunFileUpload({ runId, onUploaded }: { runId: string; onUploaded: () => void }) {
  const { text } = useLocale()
  const [entries, setEntries] = useState<UploadEntry[]>([])
  const [busy, setBusy] = useState(false)
  const pending = entries.some((entry) => entry.state === 'wachtend')

  async function upload() {
    setBusy(true)
    try {
      await uploadSequentially(entries, (file) => api.uploadOnboardingFile(runId, file), setEntries)
      onUploaded()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="run-section upload" aria-label={text({ en: 'Add files', nl: 'Bestanden toevoegen' })}>
      <h2>{text({ en: 'Add files', nl: 'Bestanden toevoegen' })}</h2>
      <input
        type="file"
        multiple
        accept={ONBOARDING_ACCEPT}
        aria-label={text({ en: 'Choose files', nl: 'Bestanden kiezen' })}
        disabled={busy}
        onChange={(e) => setEntries(toEntries(Array.from(e.target.files ?? [])))}
      />
      <UploadList entries={entries} />
      <div className="row">
        <Button variant="primary" busy={busy} disabled={!pending} onClick={() => void upload()}>
          <Upload size={14} aria-hidden="true" /> {text({ en: 'Upload', nl: 'Uploaden' })}
        </Button>
      </div>
    </section>
  )
}
