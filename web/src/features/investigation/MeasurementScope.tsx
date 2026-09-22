import { useState } from 'react'
import type { MeasurementScope, OnboardingQuestion, Source } from '../../api/types'
import { Field } from '../../components/ui'
import { SOURCE_LOCAL_LABEL, periodValue, timeBasisOf } from '../../lib/timeBasis'
import { useLocale } from '../../lib/locale'
import type { Locale } from '../../lib/locale'

/** Ready time-series sources that expose established channels. */
export function measurableSources(sources: Source[] | null): Source[] {
  return (sources ?? []).filter(
    (source) => source.kind === 'timeseries' && source.status === 'ready' && (source.metadata.channels?.length ?? 0) > 0,
  )
}

/**
 * Draft as typed; `toScope` turns it into the wire payload or nothing.
 * `exact` marks bounds that already are wire values (a starter question's
 * backend-validated scope): they are sent verbatim, never re-converted.
 */
export interface ScopeDraft {
  sourceId: string
  channel: string
  start: string
  end: string
  exact?: boolean
}

export const EMPTY_SCOPE: ScopeDraft = { sourceId: '', channel: '', start: '', end: '' }

/** Starter question scope → draft; older questions without one give null. */
export function scopeFromQuestion(question: Pick<OnboardingQuestion, 'measurement'>): ScopeDraft | null {
  const m = question.measurement
  if (!m || !m.source_id || !m.channel) return null
  return { sourceId: m.source_id, channel: m.channel, start: m.start ?? '', end: m.end ?? '', exact: true }
}

/**
 * Wire payload for `QuestionInput.measurement`. Without a source and channel
 * nothing is sent, so the whole-file default applies. Period bounds follow the
 * source's time basis: source-local strings are passed exactly as typed.
 */
export function toScope(draft: ScopeDraft, sources: Source[] | null): MeasurementScope | undefined {
  if (!draft.sourceId || !draft.channel) return undefined
  const source = sources?.find((item) => item.id === draft.sourceId)
  const basis = timeBasisOf(source?.metadata.time_basis)
  const start = draft.exact ? draft.start.trim() : periodValue(draft.start, basis)
  const end = draft.exact ? draft.end.trim() : periodValue(draft.end, basis)
  return { source_id: draft.sourceId, channel: draft.channel, ...(start ? { start } : {}), ...(end ? { end } : {}) }
}

/** Plain-language statement of what the question is constrained to. */
export function describeScope(scope: MeasurementScope | undefined, sources: Source[] | null, locale: Locale = 'en'): string {
  const text = (en: string, nl: string) => locale === 'nl' ? nl : en
  const sourceLocalLabel = text('Source-local time · timezone unknown', SOURCE_LOCAL_LABEL)
  if (!scope) return text('No measurement period selected. The full-file summary will be used.', 'Geen meetperiode gekozen. De samenvatting van het hele bestand wordt gebruikt.')
  if (sources === null) return text('Loading sources to show the measurement period…', 'Bronnen laden om de meetperiode te tonen…')
  const source = sources?.find((item) => item.id === scope.source_id)
  const channel = source?.metadata.channels?.find((item) => item.column === scope.channel)
  const name = source?.filename ?? scope.source_id
  const label = channel ? `${channel.label || channel.column} [${channel.unit}]` : scope.channel
  const basis = timeBasisOf(source?.metadata.time_basis)
  const period =
    scope.start || scope.end
      ? locale === 'nl'
        ? ` van ${scope.start ?? 'begin'} tot en met ${scope.end ?? 'einde'}${basis === 'source_local' ? ` (${sourceLocalLabel})` : ' (expliciete UTC-offset)'}`
        : ` from ${scope.start ?? 'start'} to ${scope.end ?? 'end'}${basis === 'source_local' ? ` (${sourceLocalLabel})` : ' (explicit UTC offset)'}`
      : text(' for the whole file', ' over het hele bestand')
  const missing = source ? '' : text(' This source is not in the current machine source list.', ' Deze bron staat niet in de huidige bronnenlijst van de machine.')
  return `${text('Measurement calculation limited to', 'Meetberekening beperkt tot')} ${name} · ${label}${period}.${missing}`
}

/** A prefill applies to exactly one investigation; any other id gets nothing. */
export function scopeForInvestigation(
  prefill: { investigationId: string; scope: ScopeDraft | null } | null,
  investigationId: string | null,
): ScopeDraft | undefined {
  if (!prefill || !investigationId || prefill.investigationId !== investigationId) return undefined
  return prefill.scope ?? undefined
}

/** Why sending must wait, or null. Only a prefilled exact scope depends on the source list. */
export function scopeBlockReason(draft: ScopeDraft, sources: Source[] | null, locale: Locale = 'en'): string | null {
  if (draft.exact && draft.sourceId && sources === null) return locale === 'nl' ? 'Bronnen van de machine worden geladen; de meetperiode van deze startvraag wordt daarna getoond.' : 'Machine sources are loading; the measurement period will appear next.'
  return null
}

interface Props {
  sources: Source[] | null
  draft: ScopeDraft
  onDraft: (draft: ScopeDraft) => void
  disabled: boolean
}

/** Optional 'Meetperiode voor deze vraag': ready channels of this machine only. */
export function MeasurementScopeForm({ sources, draft, onDraft, disabled }: Props) {
  const { locale, text } = useLocale()
  const [open, setOpen] = useState(Boolean(draft.exact))
  const candidates = measurableSources(sources)
  const selected = candidates.find((source) => source.id === draft.sourceId) ?? null
  const basis = timeBasisOf(selected?.metadata.time_basis)
  const sourceLocalLabel = text({ en: 'Source-local time · timezone unknown', nl: SOURCE_LOCAL_LABEL })
  if (candidates.length === 0 && !draft.exact) return null
  const scope = toScope(draft, sources)
  const block = scopeBlockReason(draft, sources, locale)

  return (
    <section className="measurement-scope" aria-label={text({ en: 'Measurement period for this question', nl: 'Meetperiode voor deze vraag' })}>
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)} disabled={disabled}>
        {open ? text({ en: 'Hide measurement period', nl: 'Meetperiode verbergen' }) : text({ en: 'Measurement period for this question (optional)', nl: 'Meetperiode voor deze vraag (optioneel)' })}
      </button>
      {draft.exact && draft.sourceId && (
        <p className="small">
          {text({ en: 'Exact measurement period from the starter question.', nl: 'Exacte meetperiode uit de startvraag.' })}
          {' '}
          <button type="button" className="link" disabled={disabled} onClick={() => onDraft(EMPTY_SCOPE)}>
            {text({ en: 'Clear measurement period', nl: 'Meetperiode loslaten' })}
          </button>
        </p>
      )}
      {open && !draft.exact && (
        <div className="measurement-scope-grid">
          <Field label={text({ en: 'Source', nl: 'Bron' })}>
            <select
              value={draft.sourceId}
              disabled={disabled}
              onChange={(e) => onDraft({ ...EMPTY_SCOPE, sourceId: e.target.value })}
            >
              <option value="">{text({ en: 'None (whole file)', nl: 'Geen (heel bestand)' })}</option>
              {candidates.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.filename}
                </option>
              ))}
            </select>
          </Field>
          {selected && (
            <Field label={text({ en: 'Channel', nl: 'Kanaal' })}>
              <select value={draft.channel} disabled={disabled} onChange={(e) => onDraft({ ...draft, channel: e.target.value })}>
                <option value="">{text({ en: 'Choose a channel', nl: 'Kies een kanaal' })}</option>
                {(selected.metadata.channels ?? []).map((channel) => (
                  <option key={channel.column} value={channel.column}>
                    {channel.label || channel.column} [{channel.unit}]
                  </option>
                ))}
              </select>
            </Field>
          )}
          {selected && (
            <>
              <Field
                label={text({ en: 'From (inclusive)', nl: 'Van (inclusief)' })}
                hint={basis === 'source_local' ? `${sourceLocalLabel}; ${text({ en: 'sent exactly as typed.', nl: 'exact zoals getypt verzonden.' })}` : text({ en: 'Your browser time zone, sent as a UTC instant.', nl: 'Uw browserzone, verzonden als UTC-moment.' })}
              >
                <input type="datetime-local" value={draft.start} disabled={disabled} onChange={(e) => onDraft({ ...draft, start: e.target.value })} />
              </Field>
              <Field label={text({ en: 'To (inclusive)', nl: 'Tot en met (inclusief)' })}>
                <input type="datetime-local" value={draft.end} disabled={disabled} onChange={(e) => onDraft({ ...draft, end: e.target.value })} />
              </Field>
            </>
          )}
        </div>
      )}
      <p className="meta" role="status">{block ?? describeScope(scope, sources, locale)}</p>
    </section>
  )
}
