import { useState } from 'react'
import type { FormEvent } from 'react'
import type { SeriesQuery, SourceChannel } from '../../api/types'
import { Button, Field } from '../../components/ui'
import { SOURCE_LOCAL_LABEL, periodValue } from '../../lib/timeBasis'
import type { TimeBasis } from '../../lib/timeBasis'

interface Props {
  channels: SourceChannel[]
  value: SeriesQuery
  onChange: (query: SeriesQuery) => void
  /** Source-local bounds are sent unchanged; absolute ones as UTC instants. */
  basis?: TimeBasis
}

/** Absolute-basis conversion kept for callers without a basis. */
export function toIsoOrBlank(local: string): string {
  return periodValue(local, 'absolute')
}

/**
 * Channel and inclusive period selection for GET /sources/{id}/series.
 * Only established channels are offered; without them the server default applies.
 */
export function SeriesControls({ channels, value, onChange, basis = 'absolute' }: Props) {
  const [channel, setChannel] = useState(value.channel ?? '')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')

  function apply(event: FormEvent) {
    event.preventDefault()
    onChange({ channel, start: periodValue(start, basis), end: periodValue(end, basis) })
  }

  return (
    <form className="series-controls" onSubmit={apply} aria-label="Series channel and period">
      {channels.length > 0 && (
        <Field label="Channel">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">Mapped default</option>
            {channels.map((item) => (
              <option key={item.column} value={item.column}>
                {item.label || item.column} [{item.unit}]
              </option>
            ))}
          </select>
        </Field>
      )}
      <Field
        label="From (inclusive)"
        hint={basis === 'source_local' ? `${SOURCE_LOCAL_LABEL}; sent exactly as typed.` : "Interpreted in your browser's zone and sent as a UTC instant."}
      >
        <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
      </Field>
      <Field label="To (inclusive)">
        <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
      <div className="row">
        <Button type="submit">Apply</Button>
        {(value.channel || value.start || value.end) && (
          <Button
            variant="ghost"
            onClick={() => {
              setChannel('')
              setStart('')
              setEnd('')
              onChange({})
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}
