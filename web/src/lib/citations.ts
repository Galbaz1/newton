import type { Evidence } from '../api/types'

/**
 * One bracketed citation: `[E1]` or a group such as `[E1, E2]`. Digits and
 * group size are bounded so hostile input cannot produce huge matches, and the
 * pattern has no nested quantifiers over overlapping classes (no backtracking
 * blow-up).
 */
const GROUP = /\[(E\d{1,4}(?:\s{0,3},\s{0,3}E\d{1,4}){0,19})\]/g

export type Segment = { type: 'text'; text: string } | { type: 'citations'; markers: string[] }

/**
 * Resolves a marker such as `E2`. The contract maps markers to evidence IDs;
 * when the server uses opaque IDs instead, fall back to the 1-based position.
 * Returns null for a marker no evidence backs, which the UI shows as invalid.
 */
export function resolveMarker(marker: string, evidence: Evidence[]): Evidence | null {
  const byId = evidence.find((item) => item.id === marker)
  if (byId) return byId
  if (evidence.some((item) => /^E\d+$/.test(item.id))) return null
  return evidence[Number(marker.slice(1)) - 1] ?? null
}

/** Label shown on a card: the marker when the ID is one, else its position. */
export function evidenceLabel(item: Evidence, index: number): string {
  return /^E\d+$/.test(item.id) ? item.id : `E${index + 1}`
}

/** Splits plain text into text and citation-group segments. No HTML, no Markdown. */
export function splitCitations(text: string): Segment[] {
  const segments: Segment[] = []
  let cursor = 0
  for (const match of text.matchAll(GROUP)) {
    const group = match[1]
    if (!group) continue
    if (match.index > cursor) segments.push({ type: 'text', text: text.slice(cursor, match.index) })
    segments.push({ type: 'citations', markers: group.split(',').map((part) => part.trim()) })
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) segments.push({ type: 'text', text: text.slice(cursor) })
  return segments
}
