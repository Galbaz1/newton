import { Send } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { ProviderInfo } from '../../api/types'
import { Button, Notice } from '../../components/ui'

interface Props {
  draft: string
  onDraft: (value: string) => void
  providers: ProviderInfo[] | null
  providersError: string | null
  model: string
  onModel: (id: string) => void
  pending: boolean
  /** Sending is disabled with this explanation while it is set. */
  blockedReason?: string | null
  onSend: () => void
}

/** Question input and closed-model selector fed by GET /health providers. */
export function Composer(props: Props) {
  const { draft, onDraft, providers, providersError, model, onModel, pending, blockedReason = null, onSend } = props
  const available = providers?.filter((provider) => provider.available) ?? []
  const canSend = draft.trim().length > 0 && model !== '' && !pending && !blockedReason

  function submit(event: FormEvent) {
    event.preventDefault()
    if (canSend) onSend()
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && canSend) onSend()
  }

  return (
    <form className="composer" onSubmit={submit}>
      {providersError && <Notice tone="error">Model list unavailable: {providersError}</Notice>}
      {providers && available.length === 0 && (
        <Notice tone="warning">
          No model provider is available on this server, so questions cannot be answered. Check the
          backend provider configuration.
        </Notice>
      )}
      {blockedReason && <Notice tone="info">{blockedReason}</Notice>}
      <textarea
        aria-label="Question about this machine"
        placeholder="Ask about this machine. Answers cite the sources they used."
        rows={3}
        value={draft}
        disabled={pending}
        onChange={(e) => onDraft(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="row composer-actions">
        <select aria-label="Model" value={model} onChange={(e) => onModel(e.target.value)} disabled={pending}>
          {model === '' && <option value="">No model available</option>}
          {providers?.map((provider) => (
            <option key={provider.id} value={provider.id} disabled={!provider.available}>
              {provider.label}
              {provider.available ? '' : ' (unavailable)'}
            </option>
          ))}
        </select>
        <Button type="submit" variant="primary" busy={pending} disabled={!canSend}>
          <Send size={14} aria-hidden="true" /> {pending ? 'Waiting for answer…' : 'Ask'}
        </Button>
      </div>
      <p className="meta">
        Your question, machine context and selected evidence, including retrieved page images,
        are sent to the chosen model to answer.
      </p>
    </form>
  )
}
