import type { Evidence, Source, SourceKind } from '../../api/types'

/** What the inspector shows: a source as uploaded, or one cited evidence item. */
export interface InspectTarget {
  sourceId: string
  filename: string
  kind: SourceKind
  revision: string
  version: number
  /** Present for evidence: the label, excerpt and cited page. */
  citation?: { label: string; excerpt: string; page: number | null }
  seriesUrl?: string | null
  /** Complete historical evidence, including its own hash and derivation snapshot. */
  evidence?: Evidence
}

export function targetFromSource(source: Source): InspectTarget {
  return {
    sourceId: source.id,
    filename: source.filename,
    kind: source.kind,
    revision: source.revision,
    version: source.version,
  }
}

export function targetFromEvidence(evidence: Evidence, label: string): InspectTarget {
  return {
    sourceId: evidence.source_id,
    filename: evidence.filename,
    kind: evidence.kind,
    revision: evidence.revision,
    version: evidence.source_version,
    citation: { label, excerpt: evidence.excerpt, page: evidence.page ?? null },
    seriesUrl: evidence.series_url,
    evidence,
  }
}
