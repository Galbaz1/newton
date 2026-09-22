import { describe, expect, it } from 'vitest'
import type { Evidence } from '../api/types'
import { resolveMarker, splitCitations } from './citations'

const evidence = (id: string): Evidence => ({
  id,
  source_id: `s-${id}`,
  filename: `${id}.pdf`,
  excerpt: '',
  revision: 'A',
  source_version: 1,
  kind: 'document',
  original_url: `/api/sources/s-${id}/original`,
})

describe('splitCitations', () => {
  it('splits single and grouped markers', () => {
    expect(splitCitations('Check [E1] and [E2, E3].')).toEqual([
      { type: 'text', text: 'Check ' },
      { type: 'citations', markers: ['E1'] },
      { type: 'text', text: ' and ' },
      { type: 'citations', markers: ['E2', 'E3'] },
      { type: 'text', text: '.' },
    ])
  })

  it('ignores look-alikes', () => {
    for (const text of ['[e1]', '[E]', '[E12345]', '[E1; E2]', '[X1]', 'E1']) {
      expect(splitCitations(text)).toEqual([{ type: 'text', text }])
    }
  })

  it('stays fast on hostile input', () => {
    const hostile = `${'[E1, '.repeat(50_000)}${'['.repeat(50_000)}`
    const started = performance.now()
    splitCitations(hostile)
    expect(performance.now() - started).toBeLessThan(1000)
  })
})

describe('resolveMarker', () => {
  it('matches marker IDs and rejects unknown ones', () => {
    const list = [evidence('E1'), evidence('E3')]
    expect(resolveMarker('E3', list)?.id).toBe('E3')
    // E2 must not silently resolve to the second card.
    expect(resolveMarker('E2', list)).toBeNull()
  })

  it('falls back to position only for opaque IDs', () => {
    const list = [evidence('a1b2'), evidence('c3d4')]
    expect(resolveMarker('E2', list)?.id).toBe('c3d4')
    expect(resolveMarker('E9', list)).toBeNull()
  })
})
