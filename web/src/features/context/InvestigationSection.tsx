import { Plus } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Investigation } from '../../api/types'
import { Button, Notice, SectionHeader } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useLocale } from '../../lib/locale'

interface Props {
  machineId: string
  investigations: Investigation[]
  selectedId: string | null
  error: string | null
  onSelect: (id: string) => void
  onCreated: (investigation: Investigation) => void
}

/** Investigation list and creation for the selected machine. */
export function InvestigationSection(props: Props) {
  const { text } = useLocale()
  const { machineId, investigations, selectedId, error, onSelect, onCreated } = props
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setCreateError(null)
    try {
      onCreated(await api.createInvestigation(machineId, title))
      setTitle('')
    } catch (caught) {
      setCreateError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="side-section">
      <SectionHeader title={text({ en: 'Investigations', nl: 'Onderzoeken' })} />
      {error && <Notice tone="error">{error}</Notice>}
      <form className="row" onSubmit={create}>
        <input
          aria-label={text({ en: 'New investigation title (optional)', nl: 'Titel nieuw onderzoek (optioneel)' })}
          placeholder={text({ en: 'Title (optional)', nl: 'Titel (optioneel)' })}
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Button type="submit" busy={busy} aria-label={text({ en: 'Start investigation', nl: 'Onderzoek starten' })}>
          <Plus size={14} aria-hidden="true" /> {text({ en: 'Start', nl: 'Starten' })}
        </Button>
      </form>
      {createError && <Notice tone="error">{createError}</Notice>}
      {investigations.length === 0 ? (
        <p className="muted small">{text({ en: 'No investigations for this machine yet.', nl: 'Nog geen onderzoeken voor deze machine.' })}</p>
      ) : (
        <ul className="pick-list">
          {investigations.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={item.id === selectedId ? 'pick pick-active' : 'pick'}
                aria-current={item.id === selectedId ? 'true' : undefined}
                onClick={() => onSelect(item.id)}
              >
                <span className="pick-title">{item.title || text({ en: 'Untitled investigation', nl: 'Onderzoek zonder titel' })}</span>
                <span className="pick-sub">
                  {formatDateTime(item.created_at)} · {text({ en: 'scope rev.', nl: 'scope rev.' })} {item.scope_revision}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
