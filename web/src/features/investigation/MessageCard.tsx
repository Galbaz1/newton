import { FileText, Image as ImageIcon, LineChart, Tags } from 'lucide-react'
import type { Evidence, Message } from '../../api/types'
import { Badge, Notice } from '../../components/ui'
import { evidenceLabel } from '../../lib/citations'
import { formatDateTime } from '../../lib/format'
import { parseSeriesExcerpt } from '../../lib/seriesExcerpt'
import { SeriesExcerptSummary } from '../evidence/SeriesExcerptSummary'
import { AnswerMarkdown } from './AnswerMarkdown'

const kindIcons = { document: FileText, image: ImageIcon, timeseries: LineChart, annotation: Tags }

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
        <ul className="evidence-list" aria-label="Evidence">
          {message.evidence.map((item) => {
            const Icon = kindIcons[item.kind] ?? FileText
            const label = labelOf(item)
            const series = item.kind === 'timeseries' ? parseSeriesExcerpt(item.excerpt) : null
            return (
              <li key={item.id}>
                <button type="button" className="evidence" onClick={() => onInspect(item, label)}>
                  <span className="evidence-head">
                    <span className="cite">{label}</span>
                    <Icon size={13} aria-hidden="true" />
                    <span className="evidence-file">{item.filename}</span>
                    <span className="meta">
                      {item.page ? `p. ${item.page} · ` : ''}rev. {item.revision || '—'} · v
                      {item.source_version}
                    </span>
                  </span>
                  {series ? (
                    <SeriesExcerptSummary data={series} compact />
                  ) : (
                    <span className="evidence-excerpt">{item.excerpt}</span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </article>
  )
}
