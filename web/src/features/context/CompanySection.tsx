import { Plus } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Company } from '../../api/types'
import { Button, EmptyState, Field, Notice, SectionHeader } from '../../components/ui'
import { useLocale } from '../../lib/locale'

interface Props {
  companies: Company[]
  selectedId: string | null
  onSelect: (id: string) => void
  onCreated: (company: Company) => void
}

/** Company (tenant) selection and creation. */
export function CompanySection({ companies, selectedId, onSelect, onCreated }: Props) {
  const { text } = useLocale()
  const [creating, setCreating] = useState(false)
  const showForm = creating || companies.length === 0
  const selected = companies.find((c) => c.id === selectedId)

  return (
    <section className="side-section">
      <SectionHeader
        title={text({ en: 'Company', nl: 'Bedrijf' })}
        aside={
          companies.length > 0 && !creating ? (
            <button type="button" className="link" onClick={() => setCreating(true)}>
              <Plus size={13} aria-hidden="true" /> {text({ en: 'New', nl: 'Nieuw' })}
            </button>
          ) : null
        }
      />
      {companies.length === 0 && (
        <EmptyState title={text({ en: 'No company yet', nl: 'Nog geen bedrijf' })}>
          {text({ en: 'A company contains its machines, sources and investigations.', nl: 'Een bedrijf bevat machines, bronnen en onderzoeken.' })}
        </EmptyState>
      )}
      {companies.length > 0 && !creating && (
        <>
          <select
            aria-label={text({ en: 'Select company', nl: 'Selecteer bedrijf' })}
            value={selectedId ?? ''}
            onChange={(e) => onSelect(e.target.value)}
          >
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
          {selected?.description && <p className="muted small">{selected.description}</p>}
        </>
      )}
      {showForm && (
        <CompanyForm
          canCancel={companies.length > 0}
          onCancel={() => setCreating(false)}
          onCreated={(company) => {
            setCreating(false)
            onCreated(company)
          }}
        />
      )}
    </section>
  )
}

function CompanyForm({
  canCancel,
  onCancel,
  onCreated,
}: {
  canCancel: boolean
  onCancel: () => void
  onCreated: (company: Company) => void
}) {
  const { text } = useLocale()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await api.createCompany(name.trim(), description.trim()))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <Field label={text({ en: 'Company name', nl: 'Bedrijfsnaam' })}>
        <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={text({ en: 'Description', nl: 'Omschrijving' })} hint={text({ en: 'Site, production type, maintenance organisation.', nl: 'Locatie, productietype, onderhoudsorganisatie.' })}>
        <textarea
          rows={3}
          maxLength={4000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row">
        <Button type="submit" variant="primary" busy={busy}>
          {text({ en: 'Create company', nl: 'Bedrijf maken' })}
        </Button>
        {canCancel && (
          <Button variant="ghost" onClick={onCancel}>
            {text({ en: 'Cancel', nl: 'Annuleren' })}
          </Button>
        )}
      </div>
    </form>
  )
}
