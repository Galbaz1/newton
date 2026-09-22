import { useState } from 'react'
import type { FormEvent } from 'react'
import { errorMessage } from '../../api/http'
import type { Machine, MachineInput } from '../../api/types'
import { Button, Field, Notice } from '../../components/ui'
import { useLocale } from '../../lib/locale'

interface Props {
  initial?: Machine
  submitLabel: string
  /** Performs the real POST or PATCH; the form only reports its outcome. */
  onSubmit: (input: MachineInput) => Promise<void>
  onCancel?: () => void
}

/** Shared create/edit form for machine context. */
export function MachineForm({ initial, submitLabel, onSubmit, onCancel }: Props) {
  const { text } = useLocale()
  const [input, setInput] = useState<MachineInput>({
    name: initial?.name ?? '',
    manufacturer: initial?.manufacturer ?? '',
    model: initial?.model ?? '',
    description: initial?.description ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = (key: keyof MachineInput) => (event: { target: { value: string } }) =>
    setInput((current) => ({ ...current, [key]: event.target.value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit({
        name: input.name.trim(),
        manufacturer: input.manufacturer.trim(),
        model: input.model.trim(),
        description: input.description.trim(),
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <Field label={text({ en: 'Machine name', nl: 'Machinenaam' })}>
        <input required maxLength={200} value={input.name} onChange={set('name')} />
      </Field>
      <div className="grid-2">
        <Field label={text({ en: 'Manufacturer', nl: 'Fabrikant' })}>
          <input maxLength={200} value={input.manufacturer} onChange={set('manufacturer')} />
        </Field>
        <Field label={text({ en: 'Model', nl: 'Model' })}>
          <input maxLength={200} value={input.model} onChange={set('model')} />
        </Field>
      </div>
      <Field label={text({ en: 'Description', nl: 'Omschrijving' })} hint={text({ en: 'Function, location, known issues, operating conditions.', nl: 'Functie, locatie, bekende problemen, bedrijfsomstandigheden.' })}>
        <textarea rows={3} maxLength={4000} value={input.description} onChange={set('description')} />
      </Field>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row">
        <Button type="submit" variant="primary" busy={busy}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            {text({ en: 'Cancel', nl: 'Annuleren' })}
          </Button>
        )}
      </div>
    </form>
  )
}
