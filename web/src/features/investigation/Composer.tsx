import { Send } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { ProviderInfo } from '../../api/types'
import { Button, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

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

export function Composer(props: Props) {
  const { text } = useLocale()
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
      {providersError && (
        <Notice tone="error">
          {text({ en: 'Could not load available models:', nl: 'Beschikbare modellen konden niet worden geladen:' })} {providersError}
        </Notice>
      )}
      {providers && available.length === 0 && (
        <Notice tone="warning">
          {text({
            en: 'Questions are unavailable until a model provider is configured.',
            nl: 'Vragen stellen is pas mogelijk als een modelaanbieder is ingesteld.',
          })}
        </Notice>
      )}
      {blockedReason && <Notice tone="info">{blockedReason}</Notice>}
      <textarea
        aria-label={text({ en: 'Question about this machine', nl: 'Vraag over deze machine' })}
        placeholder={text({
          en: 'Ask about this machine. Answers cite the sources they used.',
          nl: 'Stel een vraag over deze machine. Antwoorden verwijzen naar de gebruikte bronnen.',
        })}
        rows={3}
        value={draft}
        disabled={pending}
        onChange={(e) => onDraft(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="row composer-actions">
        <select aria-label={text({ en: 'Model', nl: 'Model' })} value={model} onChange={(e) => onModel(e.target.value)} disabled={pending}>
          {model === '' && <option value="">{text({ en: 'No model available', nl: 'Geen model beschikbaar' })}</option>}
          {providers?.map((provider) => (
            <option key={provider.id} value={provider.id} disabled={!provider.available}>
              {provider.label}
              {provider.available ? '' : text({ en: ' (unavailable)', nl: ' (niet beschikbaar)' })}
            </option>
          ))}
        </select>
        <Button type="submit" variant="primary" busy={pending} disabled={!canSend}>
          <Send size={14} aria-hidden="true" />{' '}
          {pending
            ? text({ en: 'Waiting for answer…', nl: 'Wachten op antwoord…' })
            : text({ en: 'Ask', nl: 'Vraag stellen' })}
        </Button>
      </div>
      <p className="meta">
        {text({
          en: 'The selected model receives your question, machine context and relevant evidence, including retrieved page images.',
          nl: 'Het gekozen model ontvangt je vraag, de machinecontext en relevant bronmateriaal, waaronder opgehaalde pagina-afbeeldingen.',
        })}
      </p>
    </form>
  )
}
