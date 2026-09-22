import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../api/http'
import type { Source } from '../../api/types'
import { Button, Field, Notice } from '../../components/ui'
import { timeZones } from '../../lib/format'

/** Sample rows may arrive as arrays or as objects keyed by column name. */
function cell(row: unknown, column: string, index: number): string {
  const value = Array.isArray(row)
    ? (row as unknown[])[index]
    : row && typeof row === 'object'
      ? (row as Record<string, unknown>)[column]
      : undefined
  return value === null || value === undefined ? '' : String(value)
}

/**
 * Explicit CSV mapping. Nothing is pre-filled for unit or time zone: those are
 * user statements about the data, not something the interface may guess.
 */
export function MappingForm({ source, onSaved }: { source: Source; onSaved: (s: Source) => void }) {
  const columns = source.metadata.columns ?? []
  const previewColumns = columns.slice(0, 20)
  const rows = source.metadata.sample_rows ?? []
  const [timeColumn, setTimeColumn] = useState(source.mapping?.time_column ?? '')
  const [valueColumn, setValueColumn] = useState(source.mapping?.value_column ?? '')
  const [unit, setUnit] = useState(source.mapping?.unit ?? '')
  const [timezone, setTimezone] = useState(source.mapping?.timezone ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const mapping = {
        time_column: timeColumn,
        value_column: valueColumn,
        unit: unit.trim(),
        timezone: timezone.trim() || null,
      }
      onSaved(await api.updateSource(source.id, { mapping }))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const columnSelect = (value: string, onChange: (v: string) => void) => (
    <select required value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose…</option>
      {columns.map((column) => (
        <option key={column} value={column}>
          {column}
        </option>
      ))}
    </select>
  )

  return (
    <form className="stack mapping" onSubmit={submit}>
      {columns.length === 0 && (
        <Notice tone="warning">The server reported no columns for this file.</Notice>
      )}
      {rows.length > 0 && (
        <div className="table-scroll" tabIndex={0} aria-label="First rows of the original file">
          <table>
            <caption>
              First {rows.length} rows of the original file
              {columns.length > 20 && `; first 20 of ${columns.length} columns`}
            </caption>
            <thead>
              <tr>
                {previewColumns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {previewColumns.map((column, index) => (
                    <td key={column}>{cell(row, column, index)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="grid-2">
        <Field label="Time column">{columnSelect(timeColumn, setTimeColumn)}</Field>
        <Field label="Value column">{columnSelect(valueColumn, setValueColumn)}</Field>
        <Field label="Unit" hint="As measured, e.g. °C, bar, mm/s.">
          <input required maxLength={50} value={unit} onChange={(e) => setUnit(e.target.value)} />
        </Field>
        <Field label="Time zone" hint="IANA name. Required when timestamps have no offset.">
          <input
            list="iana-zones"
            placeholder="e.g. Europe/Amsterdam"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
        </Field>
      </div>
      <datalist id="iana-zones">
        {timeZones().map((zone) => (
          <option key={zone} value={zone} />
        ))}
      </datalist>
      {error && <Notice tone="error">{error}</Notice>}
      <Button type="submit" variant="primary" busy={busy}>
        {source.mapping ? 'Save corrected mapping' : 'Save mapping'}
      </Button>
    </form>
  )
}
