import type { Evidence } from '../../api/types'

/** Show captured provenance only; current source edits must not rewrite its meaning. */
export function EvidenceProvenance({ evidence }: { evidence: Evidence }) {
  const derivation = evidence.derivation
  return (
    <details className="evidence-provenance">
      <summary>Evidence provenance</summary>
      <dl className="provenance-fields">
        <div><dt>Original file SHA-256</dt><dd>{evidence.original_sha256 ?? 'Not recorded in this answer'}</dd></div>
        {evidence.model_input && <>
          <div><dt>PDF sent to the model</dt><dd>Original pages {evidence.model_input.original_pages.join(', ')}; copied as PDF, not transcribed</dd></div>
          <div><dt>Model input SHA-256</dt><dd>{evidence.model_input.sha256}</dd></div>
        </>}
        {derivation?.method === 'csv-all-rows-summary-v1' && <>
          <div><dt>Calculation</dt><dd>Summary of all {derivation.row_count} original data rows</dd></div>
          <div><dt>Columns at answer time</dt><dd>{derivation.mapping.time_column} → {derivation.mapping.value_column}</dd></div>
          <div><dt>Unit label at answer time</dt><dd>{derivation.mapping.unit}</dd></div>
          <div><dt>Timezone for timestamps without an offset</dt><dd>{derivation.mapping.timezone ?? 'No timezone supplied; original timestamps carry offsets'}</dd></div>
          <div><dt>Chart window</dt><dd>First {derivation.visible_row_count} original rows, in file order</dd></div>
          <div><dt>Value transformations</dt><dd>No unit conversion or interpolation</dd></div>
        </>}
        {derivation?.method === 'page-text-chunk-v1' && <>
          <div><dt>Text derivation</dt><dd>Stored page text, starting at character {derivation.offset}, up to {derivation.max_characters} characters; surrounding whitespace trimmed</dd></div>
        </>}
        {evidence.retrieval && <>
          <div><dt>Visual encoder</dt><dd>{evidence.retrieval.model}</dd></div>
          <div><dt>Encoder revision</dt><dd>{evidence.retrieval.revision}</dd></div>
          <div><dt>Page view SHA-256</dt><dd>{evidence.render_sha256 ?? 'Not recorded in this answer'}</dd></div>
        </>}
      </dl>
      {!derivation && !evidence.retrieval && !evidence.model_input && <p className="meta">Derivation details were not recorded in this answer.</p>}
      <p className="meta">This record belongs to the cited source version. It is not rebuilt from later corrections.</p>
    </details>
  )
}
