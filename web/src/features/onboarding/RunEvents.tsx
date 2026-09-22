import { useState } from 'react'
import type { OnboardingEvent, OnboardingItem } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { useLocale } from '../../lib/locale'

const INITIAL = 12

/** Chronological run log with complete messages; newest last, collapsible. */
export function RunEvents({ events, items }: { events: OnboardingEvent[]; items: OnboardingItem[] }) {
  const { text } = useLocale()
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? events : events.slice(-INITIAL)
  const filename = (itemId: string | undefined) =>
    itemId ? items.find((item) => item.id === itemId)?.filename ?? null : null

  return (
    <section className="run-section" aria-label={text({ en: 'Run log', nl: 'Logboek' })}>
      <h2>{text({ en: 'Run log', nl: 'Logboek' })} ({events.length})</h2>
      {events.length === 0 && <p className="muted small">{text({ en: 'No events yet.', nl: 'Nog geen gebeurtenissen.' })}</p>}
      {events.length > INITIAL && (
        <button type="button" className="link" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? text({ en: 'Show recent', nl: 'Alleen recente tonen' }) : text({ en: `Show all ${events.length}`, nl: `Alle ${events.length} tonen` })}
        </button>
      )}
      <ol className="event-list">
        {shown.map((event, index) => (
          <li key={`${event.at}:${index}`} className={`event event-${event.kind.replaceAll(/[^a-z0-9_-]/gi, '')}`}>
            <span className="meta">{formatDateTime(event.at)}</span>
            <span className="event-kind">{event.kind}</span>
            {filename(event.item_id) && <span className="meta">{filename(event.item_id)}</span>}
            <span className="event-message">{event.message}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
