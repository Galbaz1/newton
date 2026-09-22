import type { Evidence, Message } from '../../api/types'
import { Badge, Notice } from '../../components/ui'
import { evidenceLabel } from '../../lib/citations'
import { formatDateTime } from '../../lib/format'
import { AnswerMarkdown } from './AnswerMarkdown'

interface Props {
  message: Message
  /** Current investigation scope; older assistant answers are superseded. */
  scopeRevision: number
  contextVersion: number
  onInspect: (evidence: Evidence, label: string) => void
}

/**
 * One conversation turn. Assistant text goes through AnswerMarkdown (safe
 * Markdown, citation buttons); user text is shown verbatim as plain text.
 */
export function MessageCard({ message, scopeRevision, contextVersion, onInspect }: Props) {
  const isAssistant = message.role === 'assistant'
  const superseded =
    message.status === 'superseded' ||
    (isAssistant && (message.scope_revision !== scopeRevision || message.context_version !== contextVersion))
  const failed = message.status === 'error'
  const tone = failed ? 'error' : superseded ? 'superseded' : 'plain'
  const labelOf = (item: Evidence) => evidenceLabel(item, message.evidence.indexOf(item))

  return (
    <article className={`message message-${message.role} message-${tone}`}>
      <header className="message-head">
        <span className="message-role">{isAssistant ? 'Newton' : 'You'}</span>
        {superseded && <Badge tone="superseded">Superseded by changed context or correction</Badge>}
        {failed && <Badge tone="error">Failed</Badge>}
        <span className="meta">
          {formatDateTime(message.created_at)}
          {isAssistant && message.model ? ` · ${message.model}` : ''} · scope rev.{' '}
          {message.scope_revision} · context v{message.context_version}
        </span>
      </header>

      {isAssistant ? (
        <AnswerMarkdown text={message.text} evidence={message.evidence} onInspect={onInspect} />
      ) : (
        <p className="message-text">{message.text}</p>
      )}

      {message.warnings.map((warning) => (
        <Notice key={warning} tone="warning">
          {warning}
        </Notice>
      ))}

      {isAssistant && !failed && message.evidence.length === 0 && (
        <p className="meta">No evidence was attached to this answer. Treat it as unsupported.</p>
      )}

      {message.evidence.length > 0 && (
        <details className="message-sources">
          <summary>Sources used ({message.evidence.length})</summary>
          <ul aria-label="Evidence">
            {message.evidence.map((item) => {
              const label = labelOf(item)
              return (
                <li key={item.id}>
                  <button type="button" onClick={() => onInspect(item, label)}>
                    <span className="cite">{label}</span> {item.filename}
                    {item.page ? ` · p. ${item.page}` : ''}
                  </button>
                </li>
              )
            })}
          </ul>
        </details>
      )}
    </article>
  )
}
