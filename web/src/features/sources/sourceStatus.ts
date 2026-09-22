import type { Source, SourceStatus } from '../../api/types'
import type { Tone } from '../../components/ui'
import type { Locale } from '../../lib/locale'

interface StatusInfo {
  tone: Tone
  label: string
  /** Honest statement of what is, or is not, available for this source. */
  explain: (source: Source) => string
}

/** Single place that words source states; cards and the inspector both use it. */
function sourceStatus(locale: Locale): Record<SourceStatus, StatusInfo> {
  const text = (en: string, nl: string) => locale === 'nl' ? nl : en
  return {
  ready: {
    tone: 'ready',
    label: text('Ready', 'Gereed'),
    explain: (source) =>
      source.kind === 'timeseries'
        ? text('Mapped and ready for charts and investigations.', 'Gekoppeld en gereed voor grafieken en onderzoeken.')
        : text('Extracted text is ready for investigations.', 'Geëxtraheerde tekst is gereed voor onderzoeken.'),
  },
  needs_mapping: {
    tone: 'missing',
    label: text('Mapping needed', 'Koppeling nodig'),
    explain: () =>
      text('Choose the columns, unit and time zone to use this series.', 'Kies de kolommen, eenheid en tijdzone om deze tijdreeks te gebruiken.'),
  },
  needs_text: {
    tone: 'missing',
    label: text('No extracted text', 'Geen geëxtraheerde tekst'),
    explain: () =>
      text('No text was extracted. Open the original or page images.', 'Er is geen tekst geëxtraheerd. Open het origineel of de pagina-afbeeldingen.'),
  },
  error: {
    tone: 'error',
    label: text('Error', 'Fout'),
    explain: (source) => source.metadata.error ?? text('Processing failed. Open the original file.', 'Verwerking mislukt. Open het originele bestand.'),
  },
  quarantined: {
    tone: 'error',
    label: text('Quarantined', 'In quarantaine'),
    explain: (source) =>
      quarantineReason(source) ??
      text('This source is not used in investigations. Open it to review the finding.', 'Deze bron wordt niet gebruikt in onderzoeken. Open de bron om de bevinding te bekijken.'),
  },
  }
}

/** Full quarantine reason: onboarding reason, else error text, else non-info findings. */
export function quarantineReason(source: Source): string | null {
  const onboarding = source.metadata.onboarding?.reason?.trim()
  if (onboarding) return onboarding
  const error = source.metadata.error?.trim()
  if (error) return error
  const reasons = (source.metadata.findings ?? [])
    .filter((finding) => finding.severity.toLowerCase() !== 'info')
    .map((finding) => `${finding.code}: ${finding.message}`)
  return reasons.length ? reasons.join(' ') : null
}

export const DATA_CLASS_LABEL: Record<string, string> = {
  original: 'original',
  synthetic: 'SYNTHETIC',
  demo: 'DEMO',
  derived: 'derived',
}

export function statusInfo(source: Source, locale: Locale = 'en'): StatusInfo {
  return (
    sourceStatus(locale)[source.status] ?? {
      tone: 'neutral',
      label: String(source.status),
      explain: () => locale === 'nl' ? 'De server meldt een onbekende status.' : 'The server reported an unknown status.',
    }
  )
}

export const KIND_LABEL: Record<Source['kind'], string> = {
  document: 'Document',
  image: 'Image',
  timeseries: 'Time series',
  annotation: 'Annotation',
}
