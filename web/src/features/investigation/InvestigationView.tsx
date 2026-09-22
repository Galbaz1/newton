import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { ApiError, errorMessage } from '../../api/http'
import type { Evidence, Investigation, Machine, ProviderInfo, Source } from '../../api/types'
import { EmptyState, Notice, Spinner } from '../../components/ui'
import type { Resource } from '../../lib/useResource'
import { Composer } from './Composer'
import { CorrectionForm } from './CorrectionForm'
import { MessageCard } from './MessageCard'
import { EMPTY_SCOPE, MeasurementScopeForm, scopeBlockReason, toScope } from './MeasurementScope'
import type { ScopeDraft } from './MeasurementScope'

interface Props {
  machine: Machine
  investigation: Resource<Investigation>
  providers: ProviderInfo[] | null
  providersError: string | null
  onInspectEvidence: (evidence: Evidence, label: string) => void
  /** Refetch machine, sources and readiness after any 409 conflict. */
  onContextStale: () => void
  /** Refresh accounted usage after successful or failed provider work. */
  onRunSettled: () => void
  /** Prefilled question text (onboarding starter question); the user still submits. */
  initialDraft?: string
  /** Current machine sources, for the optional measurement scope. */
  sources?: Source[] | null
  /** Exact scope of the starter question this investigation was opened from. */
  initialScope?: ScopeDraft
}

/** Conversation for one investigation: turns, pending state, correction. */
export function InvestigationView(props: Props) {
  const { machine, investigation, providers, providersError, onInspectEvidence, onContextStale } = props
  const [draft, setDraft] = useState(props.initialDraft ?? '')
  const [scope, setScope] = useState<ScopeDraft>(props.initialScope ?? EMPTY_SCOPE)
  const scopeBlock = scopeBlockReason(scope, props.sources ?? null)
  const [model, setModel] = useState('')
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const data = investigation.data
  const messages = data?.messages ?? []

  // Default to the first available provider; never silently pick an unavailable one.
  useEffect(() => {
    if (model === '' && providers) setModel(providers.find((p) => p.available)?.id ?? '')
  }, [providers, model])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, pendingText])

  /**
   * 409 has several causes (changed context, an answer already in progress).
   * Show the server's own reason, and refresh context so the next attempt uses
   * current versions; never guess the cause and never resend automatically.
   */
  function explain(caught: unknown): string {
    if (caught instanceof ApiError && caught.status === 409) {
      onContextStale()
      return `${caught.message} Nothing was resent; the machine context shown here has been refreshed.`
    }
    return errorMessage(caught)
  }

  async function send() {
    if (!data || scopeBlock) return
    const text = draft.trim()
    setPendingText(text)
    setSendError(null)
    try {
      const measurement = toScope(scope, props.sources ?? null)
      await api.sendMessage(data.id, {
        text, model, expected_context_version: machine.context_version, ...(measurement ? { measurement } : {}),
      })
      setDraft('')
    } catch (caught) {
      // The draft is kept so nothing is lost; the request is never replayed automatically.
      setSendError(explain(caught))
    } finally {
      await investigation.reload()
      props.onRunSettled()
      setPendingText(null)
    }
  }

  async function correct(text: string): Promise<string | null> {
    if (!data) return 'No investigation is loaded.'
    try {
      await api.sendCorrection(data.id, { text, expected_context_version: machine.context_version })
      await investigation.reload()
      return null
    } catch (caught) {
      return explain(caught)
    }
  }

  if (investigation.error && !data) {
    return (
      <Notice tone="error" onRetry={() => void investigation.reload()}>
        {investigation.error}
      </Notice>
    )
  }
  if (!data) return <Spinner label="Loading investigation…" />

  return (
    <div className="conversation">
      <header className="conversation-head">
        <h2>{data.title || 'Untitled investigation'}</h2>
        <p className="meta">
          {machine.name} · scope revision {data.scope_revision} · machine context v
          {machine.context_version}
        </p>
      </header>

      <div className="messages" aria-live="polite">
        {messages.length === 0 && pendingText === null && (
          <EmptyState title="No questions yet">
            Ask about symptoms, procedures, history or measurements. Newton answers only from this
            machine's uploaded sources and shows which ones it used.
          </EmptyState>
        )}
        {messages.map((message) => (
          <MessageCard
            key={message.id}
            message={message}
            scopeRevision={data.scope_revision}
            contextVersion={machine.context_version}
            onInspect={onInspectEvidence}
          />
        ))}
        {pendingText !== null && (
          <>
            <article className="message message-user message-pending">
              <header className="message-head">
                <span className="message-role">You</span>
                <span className="meta">sending…</span>
              </header>
              <p className="message-text">{pendingText}</p>
            </article>
            <Spinner label="Retrieving evidence and waiting for the model. This can take a while…" />
          </>
        )}
        <div ref={endRef} />
      </div>

      {sendError && <Notice tone="error">{sendError}</Notice>}
      {investigation.error && <Notice tone="error">{investigation.error}</Notice>}
      <MeasurementScopeForm sources={props.sources ?? null} draft={scope} onDraft={setScope} disabled={pendingText !== null} />
      <Composer
        draft={draft}
        onDraft={setDraft}
        providers={providers}
        providersError={providersError}
        model={model}
        onModel={setModel}
        pending={pendingText !== null}
        blockedReason={scopeBlock}
        onSend={() => void send()}
      />
      <CorrectionForm disabled={pendingText !== null} onSubmit={correct} />
    </div>
  )
}
