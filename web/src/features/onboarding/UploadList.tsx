import { Badge } from '../../components/ui'
import type { Tone } from '../../components/ui'
import type { UploadEntry, UploadState } from './uploadQueue'
import { useLocale } from '../../lib/locale'

const TONE: Record<UploadState, Tone> = {
  wachtend: 'neutral',
  bezig: 'neutral',
  klaar: 'ready',
  fout: 'error',
  overgeslagen: 'missing',
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

/** Per-file upload progress with the complete server error for failures. */
export function UploadList({ entries }: { entries: UploadEntry[] }) {
  const { text } = useLocale()
  if (entries.length === 0) return null
  return (
    <ul className="upload-list" aria-label={text({ en: 'Selected files', nl: 'Geselecteerde bestanden' })} aria-live="polite">
      {entries.map((entry, index) => (
        <li key={`${entry.file.name}:${index}`} className={`upload-entry upload-${entry.state}`}>
          <div className="card-head">
            <span className="card-title" title={entry.file.name}>
              {entry.file.name}
            </span>
            <span className="meta">{size(entry.file.size)}</span>
            <Badge tone={TONE[entry.state]}>{entry.state}</Badge>
          </div>
          {entry.error && <p className="small upload-error">{entry.error}</p>}
        </li>
      ))}
    </ul>
  )
}
