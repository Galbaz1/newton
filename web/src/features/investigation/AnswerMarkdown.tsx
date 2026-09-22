import Markdown, { defaultUrlTransform } from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Evidence } from '../../api/types'
import { resolveMarker } from '../../lib/citations'
import { remarkCitations } from '../../lib/remarkCitations'

/** Longer answers are cut before parsing so hostile input cannot stall the UI. */
export const MAX_ANSWER_CHARS = 60_000

interface Props {
  text: string
  evidence: Evidence[]
  onInspect: (evidence: Evidence, label: string) => void
}

/**
 * Only absolute http(s) links to *other* origins stay clickable. Relative or
 * same-origin URLs could point at this app's own routes (for example an /api
 * endpoint), so model text must not be able to make them one click away.
 */
export function safeExternalHref(href: string | undefined, ownOrigin: string | null): string | null {
  if (!href || !/^https?:\/\//i.test(href)) return null
  try {
    return new URL(href).origin === ownOrigin ? null : href
  } catch {
    return null
  }
}

const ownOrigin = () => (typeof window === 'undefined' ? null : window.location.origin)

/**
 * Renders model answers as Markdown (GFM tables and lists included) with
 * evidence citations as buttons.
 *
 * Safety: react-markdown builds React elements and never injects HTML; raw HTML
 * in the answer is shown as literal text because no rehype-raw plugin is used.
 * Images are never fetched, and links are restricted by `safeExternalHref`.
 */
export function AnswerMarkdown({ text, evidence, onInspect }: Props) {
  const truncated = text.length > MAX_ANSWER_CHARS

  const components: Components = {
    span({ node: _node, children, ...rest }) {
      const marker = (rest as { 'data-citation'?: string })['data-citation']
      if (!marker) return <span>{children}</span>
      const item = resolveMarker(marker, evidence)
      if (!item) {
        return (
          <span className="cite cite-missing" title="No evidence with this marker was returned">
            {marker}?
          </span>
        )
      }
      return (
        <button
          type="button"
          className="cite"
          onClick={() => onInspect(item, marker)}
          aria-label={`Inspect evidence ${marker}: ${item.filename}`}
        >
          {marker}
        </button>
      )
    },
    a({ node: _node, href, children }) {
      const safe = safeExternalHref(href, ownOrigin())
      if (!safe) return <span className="md-unlinked">{children}</span>
      return (
        <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
          {children}
        </a>
      )
    },
    // Remote images would leak the viewer's address and fetch untrusted content.
    img({ alt }) {
      return <span className="md-unlinked">[image not loaded{alt ? `: ${alt}` : ''}]</span>
    },
    table({ node: _node, children }) {
      return (
        <div className="table-scroll">
          <table>{children}</table>
        </div>
      )
    },
  }

  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm, remarkCitations]}
        urlTransform={defaultUrlTransform}
        components={components}
      >
        {truncated ? text.slice(0, MAX_ANSWER_CHARS) : text}
      </Markdown>
      {truncated && (
        <p className="meta">Answer shortened for display ({text.length} characters received).</p>
      )}
    </div>
  )
}
