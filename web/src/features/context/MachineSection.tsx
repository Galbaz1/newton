import { Pencil, Plus } from 'lucide-react'
import { useState } from 'react'
import { api } from '../../api/client'
import type { Machine } from '../../api/types'
import { EmptyState, SectionHeader } from '../../components/ui'
import { MachineForm } from './MachineForm'
import { useLocale } from '../../lib/locale'

interface Props {
  companyId: string
  machines: Machine[]
  selected: Machine | null
  onSelect: (id: string) => void
  /** Called after a real create or update so the workspace can refetch. */
  onSaved: (machine: Machine) => void
}

/** Machine list, creation and editable machine context for one company. */
export function MachineSection({ companyId, machines, selected, onSelect, onSaved }: Props) {
  const { text } = useLocale()
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')

  return (
    <section className="side-section">
      <SectionHeader
        title={text({ en: 'Machines', nl: 'Machines' })}
        aside={
          mode === 'view' && machines.length > 0 ? (
            <button type="button" className="link" onClick={() => setMode('create')}>
              <Plus size={13} aria-hidden="true" /> {text({ en: 'New', nl: 'Nieuw' })}
            </button>
          ) : null
        }
      />

      {machines.length === 0 && mode !== 'create' && (
        <EmptyState
          title={text({ en: 'No machines yet', nl: 'Nog geen machines' })}
          action={
            <button type="button" className="link" onClick={() => setMode('create')}>
              <Plus size={13} aria-hidden="true" /> {text({ en: 'Add the first machine', nl: 'Voeg de eerste machine toe' })}
            </button>
          }
        >
          {text({ en: 'A machine groups its manuals, images, records and time series.', nl: 'Een machine groepeert handleidingen, afbeeldingen, registraties en tijdreeksen.' })}
        </EmptyState>
      )}

      {mode === 'create' && (
        <MachineForm
          submitLabel={text({ en: 'Add machine', nl: 'Machine toevoegen' })}
          onCancel={() => setMode('view')}
          onSubmit={async (input) => {
            onSaved(await api.createMachine(companyId, input))
            setMode('view')
          }}
        />
      )}

      {mode !== 'create' && machines.length > 0 && (
        <ul className="pick-list">
          {machines.map((machine) => (
            <li key={machine.id}>
              <button
                type="button"
                className={machine.id === selected?.id ? 'pick pick-active' : 'pick'}
                aria-current={machine.id === selected?.id ? 'true' : undefined}
                onClick={() => {
                  setMode('view')
                  onSelect(machine.id)
                }}
              >
                <span className="pick-title">{machine.name}</span>
                <span className="pick-sub">
                  {[machine.manufacturer, machine.model].filter(Boolean).join(' · ') ||
                    text({ en: 'Manufacturer and model not provided', nl: 'Fabrikant en model niet opgegeven' })}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected && mode === 'view' && (
        <div className="context-card">
          <div className="section-header">
            <h3>{text({ en: 'Machine context', nl: 'Machinecontext' })}</h3>
            <button type="button" className="link" onClick={() => setMode('edit')}>
              <Pencil size={12} aria-hidden="true" /> {text({ en: 'Edit', nl: 'Bewerken' })}
            </button>
          </div>
          <p className={selected.description ? 'small' : 'small muted'}>
            {selected.description || text({ en: 'No description provided.', nl: 'Geen omschrijving opgegeven.' })}
          </p>
          <p className="meta">{text({ en: 'Context version', nl: 'Contextversie' })} {selected.context_version}</p>
        </div>
      )}

      {selected && mode === 'edit' && (
        <MachineForm
          key={`${selected.id}:${selected.context_version}`}
          initial={selected}
          submitLabel={text({ en: 'Save context', nl: 'Context opslaan' })}
          onCancel={() => setMode('view')}
          onSubmit={async (input) => {
            onSaved(await api.updateMachine(selected.id, input))
            setMode('view')
          }}
        />
      )}
    </section>
  )
}
