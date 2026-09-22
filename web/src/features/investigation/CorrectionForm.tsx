import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button, Notice } from '../../components/ui'

/**
 * Scope correction. Submitting increments the investigation's scope revision
 * on the server and supersedes earlier answers; they stay visible, marked.
 */
export function CorrectionForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean
  onSubmit: (text: string) => Promise<string | null>
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    const failure = await onSubmit(text.trim())
    setBusy(false)
    setError(failure)
    if (!failure) {
      setText('')
      setOpen(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="link" onClick={() => setOpen(true)} disabled={disabled}>
        Correct this investigation (wrong machine part, period, source or assumption)
      </button>
    )
  }
  return (
    <form className="correction stack" onSubmit={submit}>
      <label className="field">
        <span className="field-label">Correction</span>
        <textarea
          required
          rows={2}
          value={text}
          placeholder="e.g. The fault was on pump P2, not P1, and only after 3 March."
          onChange={(e) => setText(e.target.value)}
        />
        <span className="field-hint">
          Earlier answers remain visible but are marked superseded.
        </span>
      </label>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row">
        <Button type="submit" variant="primary" busy={busy} disabled={!text.trim()}>
          Apply correction
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
