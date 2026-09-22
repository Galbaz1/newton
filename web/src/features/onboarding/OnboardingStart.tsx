import { Rocket } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Company, OnboardingDataClass, OnboardingRun } from '../../api/types'
import { Button, Field, Notice } from '../../components/ui'
import { UploadList } from './UploadList'
import { ONBOARDING_ACCEPT, toEntries, uploadSequentially, uploadSummary } from './uploadQueue'
import type { UploadEntry } from './uploadQueue'
import { useLocale } from '../../lib/locale'

interface Props {
  companies: Company[]
  /** Preselected company; the form also offers creating a new one. */
  companyId: string | null
  onCompanyCreated: (company: Company) => void
  /** The run to show next, after start or (with upload failures) as draft. */
  onOpened: (run: OnboardingRun) => void
  onCancel?: () => void
}

type Phase = 'form' | 'uploading' | 'review'

/**
 * 'Bedrijf onboarden': company (new or existing), optional website, data class,
 * multi-file selection and start. Files are uploaded one by one; a failed file
 * leaves the run as draft so the owner can decide, nothing is retried silently.
 */
export function OnboardingStart({ companies, companyId, onCompanyCreated, onOpened, onCancel }: Props) {
  const { text } = useLocale()
  const [useExisting, setUseExisting] = useState(companyId !== null)
  const [existingId, setExistingId] = useState(companyId ?? companies[0]?.id ?? '')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [website, setWebsite] = useState('')
  const [dataClass, setDataClass] = useState<OnboardingDataClass>('original')
  const [entries, setEntries] = useState<UploadEntry[]>([])
  const [phase, setPhase] = useState<Phase>('form')
  const [run, setRun] = useState<OnboardingRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const summary = uploadSummary(entries)
  const canSubmit = useExisting ? existingId !== '' : name.trim().length > 0

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    let createdRun: OnboardingRun | null = null
    try {
      let targetId = existingId
      if (!useExisting) {
        const company = await api.createCompany(name.trim(), description.trim())
        onCompanyCreated(company)
        targetId = company.id
        setExistingId(company.id)
        setUseExisting(true)
      }
      const created = await api.createOnboarding(targetId, {
        website: website.trim(),
        data_class: dataClass,
      })
      createdRun = created
      setRun(created)
      setPhase('uploading')
      const result = await uploadSequentially(entries, (file) => api.uploadOnboardingFile(created.id, file), setEntries)
      if (uploadSummary(result).failed > 0) {
        setPhase('review')
        return
      }
      onOpened(await api.startOnboarding(created.id))
    } catch (caught) {
      setError(errorMessage(caught))
      setPhase(createdRun ? 'review' : 'form')
    } finally {
      setBusy(false)
    }
  }

  async function startAnyway() {
    if (!run) return
    setBusy(true)
    setError(null)
    try {
      onOpened(await api.startOnboarding(run.id))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  if (phase !== 'form') {
    return (
      <section className="onboarding-start stack" aria-label={text({ en: 'Upload files', nl: 'Bestanden uploaden' })}>
        <h2 className="onboarding-title">{text({ en: 'Upload files', nl: 'Bestanden uploaden' })}</h2>
        <UploadList entries={entries} />
        {phase === 'uploading' && (
          <p className="meta" role="status">
            {summary.done} {text({ en: 'of', nl: 'van' })} {entries.length} {text({ en: 'uploaded…', nl: 'geüpload…' })}
          </p>
        )}
        {phase === 'review' && (
          <>
            <Notice tone="warning">
              {summary.failed} {text({ en: 'file(s) failed;', nl: 'bestand(en) mislukt;' })} {summary.done} {text({ en: 'uploaded. Review the draft or start with the uploaded files.', nl: 'geüpload. Bekijk het concept of start met de geüploade bestanden.' })}
            </Notice>
            {error && <Notice tone="error">{error}</Notice>}
            <div className="row wrap">
              <Button variant="primary" busy={busy} onClick={() => void startAnyway()}>
                {text({ en: 'Start anyway', nl: 'Toch starten' })}
              </Button>
              {run && (
                <Button onClick={() => onOpened(run)} disabled={busy}>
                  {text({ en: 'Open draft', nl: 'Concept openen' })}
                </Button>
              )}
            </div>
          </>
        )}
      </section>
    )
  }

  return (
    <form className="onboarding-start stack" onSubmit={submit} aria-label={text({ en: 'Onboard company', nl: 'Bedrijf onboarden' })}>
      <h2 className="onboarding-title">{text({ en: 'Onboard company', nl: 'Bedrijf onboarden' })}</h2>
      <p className="small muted">
        {text({ en: 'Newton reviews the website and uploaded sources, then prepares a company profile and starter questions.', nl: 'Newton onderzoekt de website en de geüploade bronnen en bereidt een bedrijfsprofiel en startvragen voor.' })}
      </p>
      {companies.length > 0 && (
        <fieldset className="choice-row">
          <legend className="field-label">{text({ en: 'Company', nl: 'Bedrijf' })}</legend>
          <label>
            <input type="radio" name="company-mode" checked={!useExisting} onChange={() => setUseExisting(false)} />{' '}
            {text({ en: 'New company', nl: 'Nieuw bedrijf' })}
          </label>
          <label>
            <input type="radio" name="company-mode" checked={useExisting} onChange={() => setUseExisting(true)} />{' '}
            {text({ en: 'Existing company', nl: 'Bestaand bedrijf' })}
          </label>
        </fieldset>
      )}
      {useExisting && companies.length > 0 ? (
        <Field label={text({ en: 'Existing company', nl: 'Bestaand bedrijf' })}>
          <select value={existingId} onChange={(e) => setExistingId(e.target.value)}>
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <>
          <Field label={text({ en: 'Company name', nl: 'Bedrijfsnaam' })}>
            <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={text({ en: 'Description (optional)', nl: 'Omschrijving (optioneel)' })} hint={text({ en: 'Site, production type, maintenance organisation.', nl: 'Locatie, productietype, onderhoudsorganisatie.' })}>
            <textarea rows={2} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </>
      )}
      <Field label={text({ en: 'Website (optional)', nl: 'Website (optioneel)' })} hint={text({ en: 'Newton records website claims separately from machine records.', nl: 'Newton registreert websiteclaims afzonderlijk van machineregistraties.' })}>
        <input type="url" placeholder="https://" value={website} onChange={(e) => setWebsite(e.target.value)} />
      </Field>
      <Field label={text({ en: 'Data class', nl: 'Dataklasse' })} hint={text({ en: 'Synthetic and demo data are clearly labelled.', nl: 'Synthetische en demodata worden duidelijk gelabeld.' })}>
        <select value={dataClass} onChange={(e) => setDataClass(e.target.value as OnboardingDataClass)}>
          <option value="original">{text({ en: 'Original', nl: 'Origineel' })}</option>
          <option value="synthetic">{text({ en: 'Synthetic', nl: 'Synthetisch' })}</option>
          <option value="demo">Demo</option>
        </select>
      </Field>
      <Field label={text({ en: 'Files', nl: 'Bestanden' })} hint={text({ en: 'PDF, CSV, TXT, MD, PNG, JPEG, WebP or JSON. Up to 64 MiB per file.', nl: 'PDF, CSV, TXT, MD, PNG, JPEG, WebP of JSON. Maximaal 64 MiB per bestand.' })}>
        <input
          type="file"
          multiple
          accept={ONBOARDING_ACCEPT}
          onChange={(e) => setEntries(toEntries(Array.from(e.target.files ?? [])))}
        />
      </Field>
      <UploadList entries={entries} />
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row wrap">
        <Button type="submit" variant="primary" busy={busy} disabled={!canSubmit}>
          <Rocket size={14} aria-hidden="true" /> {text({ en: 'Start onboarding', nl: 'Onboarding starten' })}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {text({ en: 'Cancel', nl: 'Annuleren' })}
          </Button>
        )}
      </div>
    </form>
  )
}
