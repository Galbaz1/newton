import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Source } from '../../api/types'
import { Button, Field, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

const MAX_BYTES = 25 * 1024 * 1024

/** Uploads one original file. Bytes are stored unchanged by the backend. */
export function UploadForm({
  machineId,
  onUploaded,
}: {
  machineId: string
  onUploaded: (source: Source) => void
}) {
  const { text } = useLocale()
  const [file, setFile] = useState<File | null>(null)
  const [revision, setRevision] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const tooLarge = file !== null && file.size > MAX_BYTES

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file || tooLarge) return
    setBusy(true)
    setError(null)
    try {
      onUploaded(await api.uploadSource(machineId, file, revision))
      setFile(null)
      setRevision('')
      if (inputRef.current) inputRef.current.value = ''
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="upload stack" onSubmit={submit}>
      <Field label={text({ en: 'Add a source', nl: 'Bron toevoegen' })} hint={text({ en: 'PDF, TXT, MD, image or CSV time series. Max 25 MiB.', nl: 'PDF, TXT, MD, afbeelding of CSV-tijdreeks. Maximaal 25 MiB.' })}>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.md,.csv,image/*"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setError(null)
          }}
        />
      </Field>
      <Field label={text({ en: 'Revision label (optional)', nl: 'Revisielabel (optioneel)' })} hint={text({ en: 'For example “Manual rev. C, 2024”.', nl: 'Bijvoorbeeld “Handleiding rev. C, 2024”.' })}>
        <input maxLength={200} value={revision} onChange={(e) => setRevision(e.target.value)} />
      </Field>
      {tooLarge && <Notice tone="error">{text({ en: 'This file is larger than the 25 MiB upload limit.', nl: 'Dit bestand is groter dan de uploadlimiet van 25 MiB.' })}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <Button type="submit" variant="primary" busy={busy} disabled={!file || tooLarge}>
        <Upload size={14} aria-hidden="true" /> {busy ? text({ en: 'Uploading…', nl: 'Uploaden…' }) : text({ en: 'Upload', nl: 'Uploaden' })}
      </Button>
    </form>
  )
}
