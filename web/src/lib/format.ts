/** Display helpers. Formatting never alters or rounds stored source values. */

// App events (uploads, messages) use the viewer's zone, always with its label.
const dateTime = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZoneName: 'short',
})
// Measurements use one fixed zone and locale so every viewer reads the same clock.
const utcDateTime = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
  timeZone: 'UTC',
})
const number = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 })

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : dateTime.format(parsed)
}

/**
 * Formats an observation time in UTC with an explicit "UTC" suffix. Display
 * only: the stored ISO string is never modified. Unparseable input is echoed.
 */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : `${utcDateTime.format(parsed)} UTC`
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : number.format(value)
}

export function formatEur(value: number): string {
  return `€${value.toFixed(2)}`
}

export function shortHash(sha256: string): string {
  return sha256.length > 12 ? `${sha256.slice(0, 12)}…` : sha256
}

/** Browser-known IANA zones for the mapping form; empty on very old browsers. */
export function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return []
  }
}
