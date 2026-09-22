import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Evidence } from '../../api/types'
import { AnswerMarkdown, safeExternalHref } from './AnswerMarkdown'

const evidence: Evidence[] = ['E1', 'E2'].map((id) => ({
  id,
  source_id: `s-${id}`,
  filename: `${id}.pdf`,
  excerpt: '',
  revision: 'A',
  source_version: 1,
  kind: 'document',
  original_url: `/api/sources/s-${id}/original`,
}))

const render = (text: string) =>
  renderToStaticMarkup(<AnswerMarkdown text={text} evidence={evidence} onInspect={() => {}} />)

describe('AnswerMarkdown', () => {
  it('renders headings, bold, lists and GFM tables', () => {
    const html = render('### Cause\n\n**Bearing** wear\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |')
    expect(html).toContain('<h3>Cause</h3>')
    expect(html).toContain('<strong>Bearing</strong>')
    expect(html).toContain('<li>one</li>')
    expect(html).toContain('<table>')
    expect(html).not.toContain('###')
  })

  it('turns single and grouped citations into buttons, also inside bold and tables', () => {
    const html = render('See [E1]. **Both [E1, E2]**\n\n| x |\n|---|\n| [E2] |')
    expect(html.match(/<button[^>]*class="cite"/g)).toHaveLength(4)
    expect(html).toContain('aria-label="Inspect evidence E2: E2.pdf"')
  })

  it('shows unknown citations as invalid and unlinked', () => {
    const html = render('Claim [E7].')
    expect(html).toContain('cite-missing')
    expect(html).toContain('E7?')
    expect(html).not.toContain('<button')
  })

  it('does not let a model-written definition hijack a citation', () => {
    const html = render('See [E1].\n\n[E1]: https://evil.example/x')
    expect(html).toContain('<button')
    expect(html).not.toContain('evil.example')
  })

  it('leaves citations inside code literal', () => {
    expect(render('`[E1]`')).not.toContain('<button')
  })

  it('never emits raw HTML, scripts or event handlers', () => {
    const html = render('<script>alert(1)</script><img src=x onerror=alert(1)>\n\n<b onclick="x()">hi</b>')
    // The HTML survives only as escaped, inert text: no real tag is produced.
    expect(html).not.toMatch(/<script|<img|<b[ >]/)
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('&lt;b onclick=')
  })

  it('does not fetch images', () => {
    const html = render('![diagram](https://tracker.example/p.png)')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('tracker.example')
    expect(html).toContain('image not loaded: diagram')
  })

  it('unlinks javascript:, relative and /api URLs but keeps external https', () => {
    const html = render('[a](javascript:alert(1)) [b](/api/auth/logout) [c](https://docs.example/p)')
    expect(html).not.toContain('javascript:')
    expect(html).not.toContain('/api/auth/logout')
    expect(html).toContain('href="https://docs.example/p"')
    expect(html).toContain('rel="noopener noreferrer nofollow"')
  })

  it('bounds very long answers', () => {
    const html = render('a'.repeat(200_000))
    expect(html.length).toBeLessThan(70_000)
    expect(html).toContain('Answer shortened for display')
  })
})

describe('safeExternalHref', () => {
  it('rejects same-origin absolute URLs', () => {
    expect(safeExternalHref('http://127.0.0.1:8100/api/auth/logout', 'http://127.0.0.1:8100')).toBeNull()
    expect(safeExternalHref('https://docs.example/p', 'http://127.0.0.1:8100')).toBe('https://docs.example/p')
    expect(safeExternalHref('//evil.example', null)).toBeNull()
  })
})
