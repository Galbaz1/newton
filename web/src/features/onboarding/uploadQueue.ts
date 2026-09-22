import { errorMessage } from '../../api/http'

/** 64 MiB per file, as fixed by the onboarding contract. */
export const ONBOARDING_MAX_BYTES = 64 * 1024 * 1024
export const ONBOARDING_ACCEPT = '.pdf,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.json'
const ACCEPTED_EXTENSIONS = ['pdf', 'csv', 'txt', 'md', 'png', 'jpg', 'jpeg', 'webp', 'json']

export type UploadState = 'wachtend' | 'bezig' | 'klaar' | 'fout' | 'overgeslagen'

export interface UploadEntry {
  file: File
  state: UploadState
  /** Full server message; never abbreviated. */
  error: string | null
}

/** Client-side reason a file cannot be sent at all; null when acceptable. */
export function rejectReason(file: File): string | null {
  if (file.size > ONBOARDING_MAX_BYTES) return 'Groter dan de limiet van 64 MiB per bestand.'
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return `Bestandstype .${extension || '?'} wordt niet ondersteund (PDF, CSV, TXT, MD, PNG, JPEG, WebP, JSON).`
  }
  return null
}

export function toEntries(files: File[]): UploadEntry[] {
  return files.map((file) => {
    const reason = rejectReason(file)
    return { file, state: reason ? 'overgeslagen' : 'wachtend', error: reason }
  })
}

/**
 * Uploads entries one at a time, reporting the whole list after every change.
 * A failed file does not stop the others; every original is kept by the server,
 * and nothing is retried automatically.
 */
export async function uploadSequentially(
  entries: UploadEntry[],
  upload: (file: File) => Promise<unknown>,
  report: (entries: UploadEntry[]) => void,
): Promise<UploadEntry[]> {
  let current = entries.map((entry) => ({ ...entry }))
  const set = (index: number, patch: Partial<UploadEntry>) => {
    current = current.map((entry, i) => (i === index ? { ...entry, ...patch } : entry))
    report(current)
  }
  for (let index = 0; index < current.length; index += 1) {
    if (current[index]?.state !== 'wachtend') continue
    set(index, { state: 'bezig', error: null })
    try {
      await upload(current[index]!.file)
      set(index, { state: 'klaar' })
    } catch (caught) {
      set(index, { state: 'fout', error: errorMessage(caught) })
    }
  }
  return current
}

export function uploadSummary(entries: UploadEntry[]) {
  const count = (state: UploadState) => entries.filter((entry) => entry.state === state).length
  return { done: count('klaar'), failed: count('fout'), skipped: count('overgeslagen'), busy: count('bezig') > 0 }
}
